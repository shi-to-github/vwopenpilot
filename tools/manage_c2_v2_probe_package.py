"""Read, install, or roll back the disabled-by-default C2 V2 cruise probe.

The default status action is read-only. Installation preserves the working V1
HCA behavior; it never starts a manual probe or automatic speed control.
"""

import argparse
import json
import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "candidate" / "device-a6eed9e-v2-probe"
STAGE = "/data/pq46_v2_probe_staging"

REMOTE = r'''
import hashlib, json, os, pathlib, subprocess, tempfile

base = pathlib.Path('/data/openpilot')
vw = base / 'selfdrive' / 'car' / 'volkswagen'
stage = pathlib.Path('/data/pq46_v2_probe_staging')
capture = pathlib.Path('/data/pq46/capture_cruise.py')
control = pathlib.Path('/data/pq46/probe_control.py')
overlay = pathlib.Path('/data/pq46/overlay_server.py')
boot = pathlib.Path('/data/pq46/boot_overlay.py')
ui = base / 'selfdrive' / 'ui' / 'ui'
diagnostics = {'capture_cruise.py': capture, 'probe_control.py': control, 'overlay_server.py': overlay}
params = pathlib.Path('/data/params/d_tmp')
mode = pathlib.Path('/data/pq46/stock_cruise_probe_mode')
command = pathlib.Path('/data/pq46/stock_cruise_probe_command')

def digest(path):
  return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def parameter(name):
  path = params / name
  return path.read_text(errors='replace').strip() if path.is_file() else None

def git(*arguments):
  return subprocess.check_output(['git', '-C', str(base), *arguments], text=True).strip()

def atomic_copy(source, destination):
  temporary = None
  try:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.pq46-v2-', dir=str(destination.parent), delete=False) as output:
      temporary = pathlib.Path(output.name)
      output.write(source.read_bytes())
      output.flush()
      os.fsync(output.fileno())
    os.chmod(str(temporary), 0o644)
    os.replace(str(temporary), str(destination))
  finally:
    if temporary is not None and temporary.exists():
      temporary.unlink()

if git('rev-parse', '--abbrev-ref', 'HEAD') != CONFIG['device_branch']:
  raise RuntimeError('Unexpected C2 branch')
if git('rev-parse', 'HEAD') != CONFIG['base_commit']:
  raise RuntimeError('Unexpected C2 commit')

paths = {name: vw / name for name in CONFIG['deploy_sha256']}
current = {name: digest(path) for name, path in paths.items()}
expected = CONFIG['preconditions_sha256']
deployed = CONFIG['deploy_sha256']
if current == expected:
  package_state = 'READY_FROM_V1'
elif current == deployed:
  package_state = 'PROBE_PRESENT'
else:
  package_state = 'FILE_MISMATCH'

held = parameter('DisableUpdates') == '1' and pathlib.Path('/data/pq46_hca_staging/update-hold.json').is_file()
state = {'package_state': package_state, 'file_sha256': current,
         'diagnostics_sha256': {name: digest(path) for name, path in diagnostics.items()},
         'startup_sha256': {'ui': digest(ui), 'boot_overlay.py': digest(boot)},
         'IsOffroad': parameter('IsOffroad'), 'DisableUpdates': parameter('DisableUpdates'),
         'update_hold_marker': held, 'UpdateAvailable': parameter('UpdateAvailable'),
         'UpdaterState': parameter('UpdaterState'),
         'probe_mode': mode.read_text().strip() if mode.is_file() else None}

if ACTION == 'status':
  print(json.dumps(state))
else:
  if parameter('IsOffroad') != '1':
    if not PARKED_IGNITION or parameter('IsOffroad') != '0':
      raise RuntimeError('C2 is not confirmed offroad')
    require_parked_ignition()
  if not held or parameter('UpdateAvailable') == '1' or parameter('UpdaterState') not in (None, 'idle'):
    raise RuntimeError('V1 update hold is required and updater must be inactive')
  if package_state == 'FILE_MISMATCH':
    raise RuntimeError('C2 files differ from both V1 and this probe package')

  if ACTION == 'validate':
    if package_state != 'READY_FROM_V1':
      raise RuntimeError('V2 probe is not ready to install from V1')
    print(json.dumps(state))
  elif ACTION == 'install':
    if package_state != 'READY_FROM_V1':
      raise RuntimeError('V2 probe is not ready to install from V1')
    if mode.is_file() or command.is_file():
      raise RuntimeError('Existing probe mode or command file must be inspected first')
    for name in ('carcontroller.py', 'hca_timer_reset.py', 'pqcan.py', 'pq_stock_cruise_probe.py'):
      if digest(stage / ('new-' + name)) != deployed[name]:
        raise RuntimeError('Staged candidate hash mismatch: ' + name)
      compile((stage / ('new-' + name)).read_bytes(), name, 'exec')
    for name in diagnostics:
      if digest(stage / ('new-' + name)) != CONFIG['diagnostics_sha256'][name]:
        raise RuntimeError('Staged diagnostic hash mismatch: ' + name)
      compile((stage / ('new-' + name)).read_bytes(), name, 'exec')
    for name in ('carcontroller.py', 'pqcan.py'):
      if digest(stage / ('old-' + name)) != expected[name]:
        raise RuntimeError('Staged V1 rollback hash mismatch: ' + name)
    if any(path.is_file() for path in diagnostics.values()):
      raise RuntimeError('Existing diagnostic tool must be inspected first')
    try:
      for name, path in diagnostics.items():
        atomic_copy(stage / ('new-' + name), path)
      atomic_copy(stage / 'new-pq_stock_cruise_probe.py', paths['pq_stock_cruise_probe.py'])
      atomic_copy(stage / 'new-pqcan.py', paths['pqcan.py'])
      atomic_copy(stage / 'new-carcontroller.py', paths['carcontroller.py'])
      if {name: digest(path) for name, path in paths.items()} != deployed:
        raise RuntimeError('Installed file hashes do not match the manifest')
    except Exception:
      atomic_copy(stage / 'old-carcontroller.py', paths['carcontroller.py'])
      atomic_copy(stage / 'old-pqcan.py', paths['pqcan.py'])
      if digest(paths['pq_stock_cruise_probe.py']) == deployed['pq_stock_cruise_probe.py']:
        paths['pq_stock_cruise_probe.py'].unlink()
      for name, path in diagnostics.items():
        if digest(path) == CONFIG['diagnostics_sha256'][name]:
          path.unlink()
      raise
    print(json.dumps({'action': 'installed', 'mode': 'V1 default', 'file_sha256': deployed}))
  elif ACTION == 'rollback':
    if package_state == 'READY_FROM_V1':
      print(json.dumps({'action': 'already_v1'}))
    elif package_state == 'PROBE_PRESENT':
      startup = CONFIG['startup_sha256']
      if digest(ui) == startup['probe_ui']:
        if digest(boot) != startup['boot_overlay.py'] or digest(stage / 'boot-old-ui') != startup['original_ui']:
          raise RuntimeError('Startup hook or backup differs from this package')
        atomic_copy(stage / 'boot-old-ui', ui)
        os.chmod(str(ui), 0o700)
        boot.unlink()
      elif digest(ui) != startup['original_ui'] or boot.is_file():
        raise RuntimeError('Unexpected C2 UI startup state')
      for name in ('carcontroller.py', 'pqcan.py'):
        if digest(stage / ('old-' + name)) != expected[name]:
          raise RuntimeError('Staged V1 rollback hash mismatch: ' + name)
      atomic_copy(stage / 'old-carcontroller.py', paths['carcontroller.py'])
      atomic_copy(stage / 'old-pqcan.py', paths['pqcan.py'])
      paths['pq_stock_cruise_probe.py'].unlink()
      for name, path in diagnostics.items():
        if digest(path) == CONFIG['diagnostics_sha256'][name]:
          path.unlink()
      if mode.is_file():
        mode.unlink()
      if command.is_file():
        command.unlink()
      if {name: digest(path) for name, path in paths.items()} != expected:
        raise RuntimeError('V1 rollback verification failed')
      if pathlib.Path('/system/bin/pm').is_file():
        env = os.environ.copy()
        env['LD_LIBRARY_PATH'] = ''
        subprocess.run(['/system/bin/pm', 'uninstall', 'nl.vwopenploot.probe'], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
      print(json.dumps({'action': 'rolled_back_to_v1', 'file_sha256': expected}))
  else:
    raise RuntimeError('Unsupported action')
'''


def ssh_prefix(args):
  return ["ssh", "-p", str(args.port), "-i", str(args.identity),
          "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
          "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=yes",
          "-o", f"UserKnownHostsFile={args.known_hosts}", f"{args.user}@{args.ip}"]


def remote_action(args, manifest, action):
  guard = (ROOT / "tools" / "c2_parked_guard.py").read_text(encoding="utf-8")
  code = (f"CONFIG = {manifest!r}\nACTION = {action!r}\n"
          f"PARKED_IGNITION = {args.parked_ignition!r}\n" + guard + "\n" + REMOTE)
  result = subprocess.run(ssh_prefix(args) + ["cd /data/openpilot && python3 -"],
                          input=code, text=True, capture_output=True, check=True)
  print(result.stdout.strip())


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
  parser.add_argument("--parked-ignition", action="store_true")
  args = parser.parse_args()
  manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))

  if args.action == "status":
    remote_action(args, manifest, "status")
    return
  if args.action == "install":
    remote_action(args, manifest, "validate")
  else:
    remote_action(args, manifest, "status")

  subprocess.run(ssh_prefix(args) + [f"mkdir -p {STAGE} && chmod 700 {STAGE}"], check=True)
  sources = [(PACKAGE / "deploy" / name, "new-" + name)
             for name in manifest["deploy_sha256"]]
  sources += [(PACKAGE / "rollback" / name, "old-" + name)
              for name in ("carcontroller.py", "pqcan.py")]
  sources += [(PACKAGE / "diagnostics" / name, "new-" + name)
              for name in manifest["diagnostics_sha256"]]
  sources.append((PACKAGE / "rollback" / "ui", "boot-old-ui"))
  for source, remote_name in sources:
    target = f"{args.user}@{args.ip}:{STAGE}/{remote_name}"
    scp = ["scp", "-q", "-O", "-P", str(args.port), "-i", str(args.identity),
           "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
           "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={args.known_hosts}",
           str(source), target]
    subprocess.run(scp, check=True)
  remote_action(args, manifest, args.action)
  remote_action(args, manifest, "status")
  print("File change is on disk only. Restart C2 while parked, then verify status again.")


if __name__ == "__main__":
  try:
    main()
  except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
    if isinstance(error, subprocess.CalledProcessError) and error.stderr:
      print(error.stderr.strip(), file=sys.stderr)
    else:
      print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)
