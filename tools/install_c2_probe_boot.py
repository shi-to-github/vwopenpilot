"""Install guarded EON UI startup for the optional PQ46 probe overlay."""

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

import manage_c2_v2_probe_package as manager


PACKAGE = manager.PACKAGE
ORIGINAL = PACKAGE / "rollback" / "ui"
PATCHED = PACKAGE / "deploy" / "ui"
BOOT = PACKAGE / "diagnostics" / "boot_overlay.py"
OLD_HOOK = b'''# PQ46 probe overlay startup (test mode remains OFF on boot)\nif [ -f /data/pq46/boot_overlay.py ]; then\n  (LD_LIBRARY_PATH= PYTHONPATH=/data/openpilot python3 /data/pq46/boot_overlay.py >/data/pq46/boot_overlay.stdout 2>/data/pq46/boot_overlay.stderr </dev/null) &\nfi\n\n'''
HOOK = b'''# PQ46 probe overlay startup (test mode remains OFF on boot)\nif [ -f /data/pq46/boot_overlay.py ]; then\n  (PYTHONPATH=/data/openpilot python3 /data/pq46/boot_overlay.py >/data/pq46/boot_overlay.stdout 2>/data/pq46/boot_overlay.stderr </dev/null) &\nfi\n\n'''


def digest(path):
  return hashlib.sha256(path.read_bytes()).hexdigest()


def ssh(args, command, code=None):
  result = subprocess.run(manager.ssh_prefix(args) + [command], input=code,
                          text=True, encoding="utf-8", errors="replace",
                          capture_output=True, check=True)
  return result.stdout.strip()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--ip", required=True)
  parser.add_argument("--port", type=int, default=8022)
  parser.add_argument("--user", default="root")
  parser.add_argument("--identity", type=pathlib.Path,
                      default=pathlib.Path.home() / ".ssh" / "vwopenploot_c2_id_rsa")
  parser.add_argument("--known-hosts", type=pathlib.Path,
                      default=pathlib.Path.home() / ".ssh" / "known_hosts_vwopenploot_c2")
  args = parser.parse_args()

  original = ORIGINAL.read_bytes()
  anchor = b'if [ $NAV == "0" ] && [ -f /data/openpilot/selfdrive/ui/_ui_nonav ]; then\n'
  if original.count(anchor) != 1 or HOOK in original:
    raise RuntimeError("Unexpected original UI launcher")
  patched = original.replace(anchor, HOOK + anchor)
  PATCHED.write_bytes(patched)
  compile(BOOT.read_bytes(), str(BOOT), "exec")
  config = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
  check = "CONFIG = " + repr(config) + "\nACTION = 'status'\nPARKED_IGNITION = False\n" + manager.REMOTE
  status = json.loads(ssh(args, "cd /data/openpilot && python3 -", check))
  if status["package_state"] != "PROBE_PRESENT" or status["probe_mode"] != "0":
    raise RuntimeError("Probe package must be installed with test mode OFF")
  if status["IsOffroad"] == "0":
    guard = manager.ROOT.joinpath("tools/c2_parked_guard.py").read_text(encoding="utf-8")
    ssh(args, "cd /data/openpilot && python3 -", guard + "\nrequire_parked_ignition()\n")
  elif status["IsOffroad"] != "1":
    raise RuntimeError("Unknown road state")

  previous_patched = original.replace(anchor, OLD_HOOK + anchor)
  expected = {"ui": digest(ORIGINAL), "patched_ui": digest(PATCHED),
              "previous_ui": hashlib.sha256(previous_patched).hexdigest(), "boot": digest(BOOT)}
  state = json.loads(ssh(args, "python3 -", '''
import hashlib, json, pathlib
def digest(path):
  p = pathlib.Path(path)
  return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
print(json.dumps({'ui': digest('/data/openpilot/selfdrive/ui/ui'),
                  'boot': digest('/data/pq46/boot_overlay.py')}))
'''))
  if state == {"ui": expected["patched_ui"], "boot": expected["boot"]}:
    print("Boot overlay hook already installed")
    return
  if state not in ({"ui": expected["ui"], "boot": None},
                   {"ui": expected["previous_ui"], "boot": expected["boot"]}):
    raise RuntimeError("Device UI launcher or boot helper differs from expected files")

  stage = "/data/pq46_v2_probe_staging"
  for source, name in ((ORIGINAL, "boot-old-ui"), (PATCHED, "boot-new-ui"), (BOOT, "boot-overlay.py")):
    subprocess.run(["scp", "-q", "-O", "-P", str(args.port), "-i", str(args.identity),
                    "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={args.known_hosts}",
                    str(source), f"{args.user}@{args.ip}:{stage}/{name}"], check=True)
  remote = r'''
import hashlib, os, pathlib, tempfile
stage = pathlib.Path('/data/pq46_v2_probe_staging')
ui = pathlib.Path('/data/openpilot/selfdrive/ui/ui')
boot = pathlib.Path('/data/pq46/boot_overlay.py')
def digest(path):
  return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
for name, key in [('boot-old-ui', 'ui'), ('boot-new-ui', 'patched_ui'), ('boot-overlay.py', 'boot')]:
  if digest(stage / name) != EXPECTED[key]:
    raise RuntimeError('Staged file mismatch: ' + name)
previous = ui.read_bytes()
upgrade = digest(ui) == EXPECTED['previous_ui'] and digest(boot) == EXPECTED['boot']
if not upgrade and (digest(ui) != EXPECTED['ui'] or boot.exists()):
  raise RuntimeError('Existing UI or helper changed')
compile((stage / 'boot-overlay.py').read_bytes(), 'boot_overlay.py', 'exec')
with tempfile.NamedTemporaryFile(dir=str(ui.parent), prefix='.pq46-ui-', delete=False) as output:
  temp_ui = pathlib.Path(output.name)
  output.write((stage / 'boot-new-ui').read_bytes())
  output.flush()
  os.fsync(output.fileno())
os.chmod(str(temp_ui), 0o700)
if not upgrade:
  boot.write_bytes((stage / 'boot-overlay.py').read_bytes())
try:
  os.replace(str(temp_ui), str(ui))
  if digest(ui) != EXPECTED['patched_ui'] or digest(boot) != EXPECTED['boot']:
    raise RuntimeError('Installed startup hash mismatch')
except Exception:
  ui.write_bytes(previous)
  os.chmod(str(ui), 0o700)
  if not upgrade:
    boot.unlink(missing_ok=True)
  raise
print('Boot overlay startup installed; test mode remains OFF')
'''
  print(ssh(args, "python3 -", "EXPECTED = " + repr(expected) + "\n" + remote))


if __name__ == "__main__":
  try:
    main()
  except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
    print("ERROR:", error, file=sys.stderr)
    if isinstance(error, subprocess.CalledProcessError) and error.stderr:
      print(error.stderr.strip(), file=sys.stderr)
    sys.exit(1)
