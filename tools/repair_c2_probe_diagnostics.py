"""One-time guarded replacement of the first on-device trace recorder build."""

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time

import manage_c2_v2_probe_package as manager


ROOT = pathlib.Path(__file__).resolve().parents[1]
OLD = {
  "capture_cruise.py": "94633b8763b9d5de8306996d44857b0d1c4f15ce3c62631df211960669766808",
  "overlay_server.py": "1affe4efe6abf542e0a3bbab978b313bebe92a61e245039834d3aad1c9b1069e",
}
STAGE = "/data/pq46_v2_probe_staging"


def ssh(args, command, code=None):
  return subprocess.run(manager.ssh_prefix(args) + [command], input=code,
                        text=True, encoding="utf-8", errors="replace",
                        capture_output=True, check=True).stdout.strip()


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
  manifest = json.loads(manager.PACKAGE.joinpath("manifest.json").read_text(encoding="utf-8"))
  code = ("CONFIG = " + repr(manifest) + "\nACTION = 'status'\nPARKED_IGNITION = False\n" + manager.REMOTE)
  state = json.loads(ssh(args, "cd /data/openpilot && python3 -", code))
  if state["package_state"] != "PROBE_PRESENT" or state["probe_mode"] not in (None, "0"):
    raise RuntimeError("Probe package must be installed with test mode OFF")
  new = {name: manifest["diagnostics_sha256"][name] for name in OLD}
  installed = {name: state["diagnostics_sha256"][name] for name in OLD}
  if installed not in (OLD, new):
    raise RuntimeError("Device diagnostic files differ from both known builds")
  if state["IsOffroad"] == "0":
    guard = ROOT.joinpath("tools/c2_parked_guard.py").read_text(encoding="utf-8")
    ssh(args, "cd /data/openpilot && python3 -", guard + "\nrequire_parked_ignition()\n")
  elif state["IsOffroad"] != "1":
    raise RuntimeError("C2 road state is unavailable")

  try:
    ssh(args, "curl -fsS -X POST http://127.0.0.1:8765/shutdown")
  except subprocess.CalledProcessError:
    pass
  if installed == OLD:
    for name in OLD:
      source = manager.PACKAGE / "diagnostics" / name
      subprocess.run(["scp", "-q", "-O", "-P", str(args.port), "-i", str(args.identity),
                      "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                      "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={args.known_hosts}",
                      str(source), f"{args.user}@{args.ip}:{STAGE}/repair-{name}"], check=True)
    repair = r'''
import hashlib, os, pathlib, tempfile
stage = pathlib.Path('/data/pq46_v2_probe_staging')
root = pathlib.Path('/data/pq46')
def digest(path):
  return hashlib.sha256(path.read_bytes()).hexdigest()
def replace(path, data):
  with tempfile.NamedTemporaryFile(dir=str(root), prefix='.probe-fix-', delete=False) as output:
    temporary = pathlib.Path(output.name)
    output.write(data)
    output.flush()
    os.fsync(output.fileno())
  os.chmod(str(temporary), 0o644)
  os.replace(str(temporary), str(path))
previous = {}
for name, expected in OLD.items():
  target = root / name
  staged = stage / ('repair-' + name)
  if digest(target) != expected or digest(staged) != NEW[name]:
    raise RuntimeError('Diagnostic hash mismatch: ' + name)
  data = staged.read_bytes()
  compile(data, name, 'exec')
  previous[name] = target.read_bytes()
try:
  for name in OLD:
    replace(root / name, (stage / ('repair-' + name)).read_bytes())
  if any(digest(root / name) != NEW[name] for name in OLD):
    raise RuntimeError('Post-copy diagnostic hash mismatch')
except Exception:
  for name, data in previous.items():
    replace(root / name, data)
  raise
print('diagnostics repaired')
'''
    ssh(args, "python3 -", "OLD = " + repr(OLD) + "\nNEW = " + repr(new) + "\n" + repair)
  start = '''
import os, subprocess
env = os.environ.copy()
env['PYTHONPATH'] = '/data/openpilot'
with open('/data/pq46/overlay_server.stdout', 'ab') as out, open('/data/pq46/overlay_server.stderr', 'ab') as err:
  process = subprocess.Popen(['python3', '/data/pq46/overlay_server.py'], cwd='/data/openpilot', env=env,
                             stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                             close_fds=True, start_new_session=True)
print(process.pid)
'''
  ssh(args, "python3 -", start)
  for _ in range(6):
    time.sleep(1)
    try:
      current = json.loads(ssh(args, "curl -fsS http://127.0.0.1:8765/status"))
      if current.get("enabled") is False:
        print(json.dumps(current, ensure_ascii=False))
        break
    except (subprocess.CalledProcessError, json.JSONDecodeError):
      continue
  else:
    raise RuntimeError("Repaired overlay server did not start")


if __name__ == "__main__":
  try:
    main()
  except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
    print("ERROR:", error, file=sys.stderr)
    if isinstance(error, subprocess.CalledProcessError) and error.stderr:
      print(error.stderr.strip(), file=sys.stderr)
    sys.exit(1)
