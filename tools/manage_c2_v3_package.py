"""Guarded V2-to-V3 upgrade/rollback. Default action is read-only status."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'candidate/device-a6eed9e-v3'
STAGE = '/data/pq46_v3_staging'

REMOTE = r'''
import hashlib, json, os, pathlib, subprocess, tempfile
from urllib.request import Request, urlopen
base = pathlib.Path('/data/openpilot')
vw = base / 'selfdrive/car/volkswagen'
stage = pathlib.Path('/data/pq46_v3_staging')
root = pathlib.Path('/data/pq46')
params = pathlib.Path('/data/params/d_tmp')
hold = pathlib.Path('/data/pq46_hca_staging/update-hold.json')
ui = base / 'selfdrive/ui/ui'
boot = root / 'boot_overlay.py'

def digest(path):
  return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def parameter(name):
  path = params / name
  return path.read_text(errors='replace').strip() if path.is_file() else None

def git(*args):
  return subprocess.check_output(['git', '-C', str(base), *args], text=True).strip()

def atomic(source, destination):
  destination.parent.mkdir(parents=True, exist_ok=True)
  with tempfile.NamedTemporaryFile(prefix='.pq46-v3-', dir=str(destination.parent), delete=False) as out:
    temp = pathlib.Path(out.name)
    out.write(source.read_bytes())
    out.flush()
    os.fsync(out.fileno())
  try:
    os.chmod(str(temp), 0o644)
    os.replace(str(temp), str(destination))
  finally:
    temp.unlink(missing_ok=True)

def app_install(path):
  env = os.environ.copy()
  env['LD_LIBRARY_PATH'] = ''
  subprocess.run(['/system/bin/am', 'force-stop', 'nl.vwopenploot.probe'], env=env,
                 capture_output=True, timeout=15, check=True)
  # Android's package service cannot read root-only SCP staging (0700/0600).
  # Keep staging private and expose only this signed APK in its normal inbox.
  inbox = pathlib.Path('/data/local/tmp/pq46-v3-install.apk')
  atomic(path, inbox)
  try:
    if digest(inbox) != digest(path):
      raise RuntimeError('Android APK inbox hash mismatch')
    result = subprocess.run(['/system/bin/pm', 'install', '-r', '-d', str(inbox)], env=env,
                            capture_output=True, timeout=90, text=True, check=False)
    if result.returncode != 0 or 'Success' not in result.stdout:
      raise RuntimeError('Android overlay install failed: ' + result.stdout + result.stderr)
  finally:
    inbox.unlink(missing_ok=True)

def stop_backends():
  for port in (8765, 8766):
    try:
      with urlopen(Request('http://127.0.0.1:%d/shutdown' % port, data=b'{}',
                           headers={'Content-Type': 'application/json'}), timeout=3) as result:
        if result.status != 200:
          raise RuntimeError('Backend shutdown rejected')
    except (OSError, TimeoutError):
      pass
  (root / 'stock_cruise_probe_mode').write_text('0', encoding='utf-8')
  (root / 'stock_cruise_probe_command').unlink(missing_ok=True)
  (root / 'auto_probe_heartbeat').unlink(missing_ok=True)
  (root / 'v3_mode.json').unlink(missing_ok=True)

if git('rev-parse', '--abbrev-ref', 'HEAD') != CONFIG['device_branch']:
  raise RuntimeError('Unexpected C2 branch')
if git('rev-parse', 'HEAD') != CONFIG['base_commit']:
  raise RuntimeError('Unexpected C2 commit')
expected, deployed = CONFIG['preconditions_sha256'], CONFIG['deploy_sha256']
paths = {name: vw / name for name in deployed}
diag = {name: root / name for name in CONFIG['diagnostics_sha256']}
current = {name: digest(path) for name, path in paths.items()}
boot_hash = digest(boot)
if current == expected and boot_hash == CONFIG['startup_sha256']['v2_boot'] and all(not p.exists() for p in diag.values()):
  state = 'READY_FROM_V2'
elif (current == deployed and boot_hash == CONFIG['startup_sha256']['v3_boot'] and
      {name: digest(path) for name, path in diag.items()} == CONFIG['diagnostics_sha256']):
  state = 'V3_PRESENT'
else:
  state = 'FILE_MISMATCH'
held = parameter('DisableUpdates') == '1' and hold.is_file()
status = {'package_state': state, 'file_sha256': current, 'boot_sha256': boot_hash,
          'ui_sha256': digest(ui), 'IsOffroad': parameter('IsOffroad'),
          'DisableUpdates': parameter('DisableUpdates'), 'update_hold': held,
          'diagnostics_sha256': {name: digest(path) for name, path in diag.items()}}
if ACTION == 'status':
  print(json.dumps(status))
else:
  if parameter('IsOffroad') != '1':
    if not PARKED_IGNITION or parameter('IsOffroad') != '0':
      raise RuntimeError('C2 is not confirmed offroad')
    require_parked_ignition()
  if not held or parameter('UpdateAvailable') == '1' or parameter('UpdaterState') not in (None, 'idle'):
    raise RuntimeError('Update hold required; updater must be inactive')
  if state == 'FILE_MISMATCH' or digest(ui) != CONFIG['startup_sha256']['ui']:
    raise RuntimeError('Device files or UI startup differ from the pinned package')
  if any(digest(vw / name) != value for name, value in CONFIG['preserved_sha256'].items()):
    raise RuntimeError('Preserved V2 module differs from the inspected baseline')
  required_state = 'READY_FROM_V2' if ACTION in ('validate', 'install') else 'V3_PRESENT'
  if state != required_state:
    raise RuntimeError('Unexpected package state for ' + ACTION + ': ' + state)
  if ACTION == 'validate':
    print(json.dumps(status))
  elif ACTION in ('install', 'rollback'):
    # Validate every staged artifact before touching device files.
    for name, value in deployed.items():
      path = stage / ('new-' + name)
      if digest(path) != value:
        raise RuntimeError('Staged V3 hash mismatch: ' + name)
      compile(path.read_bytes(), name, 'exec')
    for name, value in expected.items():
      if value is not None and digest(stage / ('old-' + name)) != value:
        raise RuntimeError('Staged V2 rollback mismatch: ' + name)
    for name, value in CONFIG['diagnostics_sha256'].items():
      path = stage / ('new-' + name)
      if digest(path) != value:
        raise RuntimeError('Staged diagnostic mismatch: ' + name)
      compile(path.read_bytes(), name, 'exec')
    for name, value in (('new-boot.py', CONFIG['startup_sha256']['v3_boot']),
                        ('old-boot.py', CONFIG['startup_sha256']['v2_boot']),
                        ('new-overlay.apk', CONFIG['apk_sha256']['v3']),
                        ('old-overlay.apk', CONFIG['apk_sha256']['v2'])):
      if digest(stage / name) != value:
        raise RuntimeError('Staged startup artifact mismatch: ' + name)
    for name in ('new-boot.py', 'old-boot.py'):
      compile((stage / name).read_bytes(), name, 'exec')

    stop_backends()
    # Matching V2/V3 files are also snapshotted on-device before mutation.
    for name, path in paths.items():
      if path.exists():
        atomic(path, stage / ('snapshot-' + name))
    atomic(boot, stage / 'snapshot-boot.py')

    def restore_v2():
      for name, path in paths.items():
        if expected[name] is None:
          path.unlink(missing_ok=True)
        else:
          atomic(stage / ('old-' + name), path)
      for path in diag.values():
        path.unlink(missing_ok=True)
      atomic(stage / 'old-boot.py', boot)
      app_install(stage / 'old-overlay.apk')

    if ACTION == 'install':
      try:
        for name, path in diag.items():
          atomic(stage / ('new-' + name), path)
        for name, path in paths.items():
          atomic(stage / ('new-' + name), path)
        atomic(stage / 'new-boot.py', boot)
        app_install(stage / 'new-overlay.apk')
        if {name: digest(path) for name, path in paths.items()} != deployed:
          raise RuntimeError('Installed V3 file verification failed')
        if digest(boot) != CONFIG['startup_sha256']['v3_boot']:
          raise RuntimeError('Installed boot verification failed')
      except Exception as original:
        try:
          restore_v2()
        except Exception as recovery:
          raise RuntimeError('Upgrade failed, and rollback also failed: %s; %s' % (original, recovery))
        raise
      result = 'installed_v3_default_base'
    else:
      restore_v2()
      if {name: digest(path) for name, path in paths.items()} != expected:
        raise RuntimeError('V2 rollback verification failed')
      result = 'rolled_back_to_v2'
    print(json.dumps({'action': result, 'reboot_required': True, 'logs_preserved': True}))
  else:
    raise RuntimeError('Unsupported action')
'''


def ssh_prefix(args):
  return ['ssh', '-p', str(args.port), '-i', str(args.identity), '-o', 'IdentitiesOnly=yes',
          '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o', 'StrictHostKeyChecking=yes',
          '-o', 'UserKnownHostsFile=' + str(args.known_hosts), args.user + '@' + args.ip]


def remote_action(args, manifest, action):
  guard = (ROOT / 'tools/c2_parked_guard.py').read_text(encoding='utf-8')
  code = 'CONFIG = %r\nACTION = %r\nPARKED_IGNITION = %r\n' % (manifest, action, args.parked_ignition)
  result = subprocess.run(ssh_prefix(args) + ['cd /data/openpilot && python3 -'],
                          input=code + guard + '\n' + REMOTE, text=True, encoding='utf-8',
                          capture_output=True, check=True)
  print(result.stdout.strip())


def sources(manifest):
  pairs = [(PACKAGE / 'deploy' / name, 'new-' + name) for name in manifest['deploy_sha256']]
  pairs += [(PACKAGE / 'rollback' / name, 'old-' + name)
            for name, value in manifest['preconditions_sha256'].items() if value is not None]
  pairs += [(PACKAGE / 'diagnostics' / name, 'new-' + name) for name in manifest['diagnostics_sha256']]
  pairs += [(PACKAGE / 'diagnostics/boot_overlay.py', 'new-boot.py'),
            (PACKAGE / 'rollback/boot_overlay.py', 'old-boot.py'),
            (PACKAGE / 'overlay/build/pq46-probe-overlay.apk', 'new-overlay.apk'),
            (ROOT / 'candidate/device-a6eed9e-v2-probe/overlay/build/pq46-probe-overlay.apk', 'old-overlay.apk')]
  return pairs


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--ip', required=True)
  parser.add_argument('--port', type=int, default=8022)
  parser.add_argument('--user', default='root')
  parser.add_argument('--identity', type=Path, default=Path.home() / '.ssh/vwopenploot_c2_id_rsa')
  parser.add_argument('--known-hosts', type=Path, default=Path.home() / '.ssh/known_hosts_vwopenploot_c2')
  parser.add_argument('--action', choices=('status', 'install', 'rollback'), default='status')
  parser.add_argument('--parked-ignition', action='store_true')
  args = parser.parse_args()
  manifest = json.loads((PACKAGE / 'manifest.json').read_text(encoding='utf-8'))
  if args.action == 'status':
    remote_action(args, manifest, 'status')
    return
  for source, _ in sources(manifest):
    if not source.is_file():
      raise RuntimeError('Missing local artifact: ' + str(source))
  # Remote validate guards run before staging and again before any mutation.
  remote_action(args, manifest, 'validate' if args.action == 'install' else 'status')
  subprocess.run(ssh_prefix(args) + ['mkdir -p %s && chmod 700 %s' % (STAGE, STAGE)], check=True)
  scp = ['scp', '-q', '-O', '-P', str(args.port), '-i', str(args.identity),
         '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
         '-o', 'UserKnownHostsFile=' + str(args.known_hosts)]
  for source, name in sources(manifest):
    subprocess.run(scp + [str(source), '%s@%s:%s/%s' % (args.user, args.ip, STAGE, name)], check=True)
  remote_action(args, manifest, args.action)
  remote_action(args, manifest, 'status')
  print('Files/APK installed; speed control OFF. Restart C2 while parked before verification.')


if __name__ == '__main__':
  try:
    main()
  except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as error:
    print(error.stderr if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error), file=sys.stderr)
    sys.exit(1)
