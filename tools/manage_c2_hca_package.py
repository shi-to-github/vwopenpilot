"""Check, install, or roll back the inspected C2 HCA test package.

Status is read-only. Install and rollback require an explicit --action value and
leave restarting the C2 to the operator.
"""

import argparse
import json
import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "candidate" / "device-a6eed9e-2s"
STAGE = "/data/pq46_hca_staging"
PARKED_GUARD = ROOT / "tools" / "c2_parked_guard.py"

REMOTE_ACTION = r'''
import hashlib, json, os, pathlib, subprocess, tempfile

base = pathlib.Path('/data/openpilot')
vw = base / 'selfdrive' / 'car' / 'volkswagen'
stage = pathlib.Path('/data/pq46_hca_staging')
params = pathlib.Path('/data/params/d_tmp')

def digest(path):
  return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def parameter(name):
  path = params / name
  return path.read_text(errors='replace').strip() if path.is_file() else None

def git(*arguments):
  return subprocess.check_output(['git', '-C', str(base), *arguments], text=True).strip()

def atomic_copy(source, destination):
  data = source.read_bytes()
  temporary = None
  try:
    with tempfile.NamedTemporaryFile(prefix='.pq46-', dir=str(vw), delete=False) as output:
      temporary = pathlib.Path(output.name)
      output.write(data)
      output.flush()
      os.fsync(output.fileno())
    os.chmod(str(temporary), 0o644)
    os.replace(str(temporary), str(destination))
  finally:
    if temporary is not None and temporary.exists():
      temporary.unlink()

if parameter('IsOffroad') != '1':
  if not PARKED_IGNITION or parameter('IsOffroad') != '0':
    raise RuntimeError('C2 is not confirmed offroad')
  require_parked_ignition()
held = parameter('DisableUpdates') == '1' and (stage / 'update-hold.json').is_file()
if (parameter('UpdateAvailable') not in (('0', None) if held else ('0',)) or
    parameter('UpdaterState') not in (('idle', None) if held else ('idle',))):
  raise RuntimeError('Updater is pending or active')
if git('rev-parse', '--abbrev-ref', 'HEAD') != CONFIG['device_branch']:
  raise RuntimeError('Device branch differs from package baseline')
if git('rev-parse', 'HEAD') != CONFIG['base_commit']:
  raise RuntimeError('Device commit differs from package baseline')

controller = vw / 'carcontroller.py'
module = vw / 'hca_timer_reset.py'
original = stage / 'carcontroller-original.py'
candidate = stage / 'carcontroller-new.py'
candidate_module = stage / 'hca_timer_reset-new.py'
base_hash = CONFIG['remote_preconditions']['carcontroller.py_sha256']
new_hash = CONFIG['deploy_sha256']['carcontroller.py']
module_hash = CONFIG['deploy_sha256']['hca_timer_reset.py']

if digest(original) != base_hash:
  raise RuntimeError('Staged rollback file hash mismatch')

if ACTION == 'install':
  if digest(controller) != base_hash or module.exists():
    raise RuntimeError('Live controller is not the inspected baseline')
  if digest(candidate) != new_hash or digest(candidate_module) != module_hash:
    raise RuntimeError('Staged candidate hash mismatch')
  compile(candidate.read_bytes(), str(candidate), 'exec')
  compile(candidate_module.read_bytes(), str(candidate_module), 'exec')
  try:
    atomic_copy(candidate_module, module)
    atomic_copy(candidate, controller)
    if digest(controller) != new_hash or digest(module) != module_hash:
      raise RuntimeError('Installed hashes differ from package manifest')
  except Exception:
    atomic_copy(original, controller)
    if digest(module) == module_hash:
      module.unlink()
    raise
  print(json.dumps({'action': 'installed', 'controller_sha256': digest(controller),
                    'module_sha256': digest(module)}))
elif ACTION == 'rollback':
  if digest(controller) == base_hash and not module.exists():
    print(json.dumps({'action': 'already_rolled_back'}))
  elif digest(controller) == new_hash and digest(module) == module_hash:
    atomic_copy(original, controller)
    module.unlink()
    if digest(controller) != base_hash or module.exists():
      raise RuntimeError('Rollback verification failed')
    print(json.dumps({'action': 'rolled_back', 'controller_sha256': digest(controller)}))
  else:
    raise RuntimeError('Live files differ from both baseline and candidate')
else:
  raise RuntimeError('Unsupported action')
'''


def ssh_prefix(args):
  return [
    "ssh", "-p", str(args.port), "-i", str(args.identity),
    "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=yes",
    "-o", f"UserKnownHostsFile={args.known_hosts}",
    f"{args.user}@{args.ip}",
  ]


def run_status(args):
  command = [sys.executable, str(ROOT / "tools" / "check_c2_hca_package.py"),
             "--ip", args.ip, "--port", str(args.port), "--user", args.user,
             "--identity", str(args.identity), "--known-hosts", str(args.known_hosts)]
  if args.parked_ignition:
    command.append("--parked-ignition")
  result = subprocess.run(command, text=True, capture_output=True)
  if result.stdout:
    print(result.stdout.rstrip())
  if result.returncode:
    message = result.stderr.strip().removeprefix("ERROR: ")
    raise RuntimeError(message or "C2 package status check failed")


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--ip", required=True)
  parser.add_argument("--port", type=int, default=8022)
  parser.add_argument("--user", default="root")
  parser.add_argument("--identity", type=pathlib.Path,
                      default=pathlib.Path.home() / ".ssh" / "vwopenploot_c2_id_rsa")
  parser.add_argument("--known-hosts", type=pathlib.Path,
                      default=pathlib.Path.home() / ".ssh" / "known_hosts_vwopenploot_c2")
  parser.add_argument("--action", choices=("status", "install", "rollback"), default="status")
  parser.add_argument("--parked-ignition", action="store_true",
                      help="Allow ignition-on installation only with live Park/standstill/disengaged checks")
  args = parser.parse_args()

  manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
  run_status(args)
  if args.action == "status":
    return

  subprocess.run(ssh_prefix(args) + [f"mkdir -p {STAGE} && chmod 700 {STAGE}"], check=True)
  files = (
    (PACKAGE / "deploy" / "carcontroller.py", "carcontroller-new.py"),
    (PACKAGE / "deploy" / "hca_timer_reset.py", "hca_timer_reset-new.py"),
    (PACKAGE / "rollback" / "carcontroller.py", "carcontroller-original.py"),
  )
  for source, remote_name in files:
    target = f"{args.user}@{args.ip}:{STAGE}/{remote_name}"
    scp = ["scp", "-q", "-O", "-P", str(args.port), "-i", str(args.identity),
           "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
           "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={args.known_hosts}",
           str(source), target]
    subprocess.run(scp, check=True)

  guard = PARKED_GUARD.read_text(encoding="utf-8")
  remote_code = (f"CONFIG = {manifest!r}\nACTION = {args.action!r}\n"
                 f"PARKED_IGNITION = {args.parked_ignition!r}\n" + guard + "\n" + REMOTE_ACTION)
  result = subprocess.run(ssh_prefix(args) + ["cd /data/openpilot && python3 -"], input=remote_code,
                          text=True, capture_output=True, check=True)
  print(result.stdout.strip())
  run_status(args)
  print("C2 files changed on disk. Restart only while parked, then run status again before driving.")


if __name__ == "__main__":
  try:
    main()
  except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
    if isinstance(error, subprocess.CalledProcessError) and error.stderr:
      print(error.stderr.strip(), file=sys.stderr)
    else:
      print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)
