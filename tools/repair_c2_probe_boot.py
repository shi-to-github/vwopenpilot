"""Replace the early-Android EON overlay startup helper with a retrying build."""

import argparse
import hashlib
import pathlib
import subprocess
import sys

import manage_c2_v2_probe_package as manager


OLD_HASH = "ce893f243a9354eed3c2b7903641855b90f145194801441eb1ccd1a38e61fe7f"
SOURCE = manager.PACKAGE / "diagnostics" / "boot_overlay.py"


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
  new_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
  current = ssh(args, "sha256sum /data/pq46/boot_overlay.py").split()[0]
  if current == new_hash:
    print("Boot helper already current")
    return
  if current != OLD_HASH:
    raise RuntimeError("Device boot helper has an unexpected hash")
  guard = manager.ROOT.joinpath("tools/c2_parked_guard.py").read_text(encoding="utf-8")
  ssh(args, "cd /data/openpilot && python3 -", guard + "\nrequire_parked_ignition()\n")
  if ssh(args, "cat /data/pq46/stock_cruise_probe_mode") != "0":
    raise RuntimeError("Test mode is active")
  subprocess.run(["scp", "-q", "-O", "-P", str(args.port), "-i", str(args.identity),
                  "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                  "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={args.known_hosts}",
                  str(SOURCE), f"{args.user}@{args.ip}:/data/pq46_v2_probe_staging/boot-overlay-repair.py"], check=True)
  remote = r'''
import hashlib, os, pathlib, tempfile
old = pathlib.Path('/data/pq46/boot_overlay.py')
staged = pathlib.Path('/data/pq46_v2_probe_staging/boot-overlay-repair.py')
def digest(p):
  return hashlib.sha256(p.read_bytes()).hexdigest()
if digest(old) != OLD or digest(staged) != NEW:
  raise RuntimeError('Boot helper hash changed')
compile(staged.read_bytes(), 'boot_overlay.py', 'exec')
with tempfile.NamedTemporaryFile(dir=str(old.parent), prefix='.pq46-boot-', delete=False) as output:
  temp = pathlib.Path(output.name)
  output.write(staged.read_bytes())
  output.flush()
  os.fsync(output.fileno())
os.chmod(str(temp), 0o600)
os.replace(str(temp), str(old))
if digest(old) != NEW:
  raise RuntimeError('Boot helper installation failed')
print('Boot helper repaired')
'''
  print(ssh(args, "python3 -", "OLD = " + repr(OLD_HASH) + "\nNEW = " + repr(new_hash) + "\n" + remote))


if __name__ == "__main__":
  try:
    main()
  except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
    print("ERROR:", error, file=sys.stderr)
    if isinstance(error, subprocess.CalledProcessError) and error.stderr:
      print(error.stderr.strip(), file=sys.stderr)
    sys.exit(1)
