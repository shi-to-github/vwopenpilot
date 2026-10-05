"""Pinned, parked-only V3 HCA r1 upgrade/rollback; leaves APK and cruise code intact."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from manage_c2_v3_package import ssh_prefix

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'candidate/device-a6eed9e-v3-hca-r1'
STAGE = '/data/pq46_hca_r1_staging'

REMOTE = r'''
import hashlib, importlib.util, json, os, pathlib, subprocess, tempfile, time
from urllib.request import Request, urlopen
stage = pathlib.Path('/data/pq46_hca_r1_staging')
base = pathlib.Path('/data/openpilot')
vw = base / 'selfdrive/car/volkswagen'
params = pathlib.Path('/data/params/d_tmp')

def digest(path):
  return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def parameter(name):
  p = params / name
  return p.read_text(errors='replace').strip() if p.is_file() else None

def atomic(source, destination):
  with tempfile.NamedTemporaryFile(dir=str(destination.parent), prefix='.hca-r1-', delete=False) as output:
    temp = pathlib.Path(output.name)
    output.write(source.read_bytes())
    output.flush()
    os.fsync(output.fileno())
  try:
    os.chmod(str(temp), 0o644)
    os.replace(str(temp), str(destination))
  finally:
    temp.unlink(missing_ok=True)

current = {name: digest(pathlib.Path(name)) for name in CONFIG['before_sha256']}
state = ('V3_BASELINE' if current == CONFIG['before_sha256'] else
         'HCA_R1_PRESENT' if current == CONFIG['after_sha256'] else 'FILE_MISMATCH')
print(json.dumps({'state': state, 'files': current, 'IsOffroad': parameter('IsOffroad'),
                  'DisableUpdates': parameter('DisableUpdates'), 'boot_s': time.monotonic()}), flush=True)
if ACTION == 'status':
  pass
else:
  if state == 'FILE_MISMATCH':
    raise RuntimeError('Device differs from pinned V3/HCA-r1 files')
  if parameter('IsOffroad') != '1':
    if not PARKED_IGNITION or parameter('IsOffroad') != '0':
      raise RuntimeError('Parked ignition or offroad required')
    require_parked_ignition()
  if (parameter('DisableUpdates') != '1' or
      not pathlib.Path('/data/pq46_hca_staging/update-hold.json').is_file() or
      parameter('UpdateAvailable') == '1' or parameter('UpdaterState') not in (None, 'idle')):
    raise RuntimeError('Update hold is not confirmed idle')
  for args, expected in ((['rev-parse', 'HEAD'], CONFIG['base_commit']),
                         (['rev-parse', '--abbrev-ref', 'HEAD'], CONFIG['device_branch'])):
    actual = subprocess.check_output(['git', '-C', str(base)] + args, text=True).strip()
    if actual != expected:
      raise RuntimeError('Unexpected device git identity')
  expected_state = ('HCA_R1_PRESENT' if ACTION == 'rollback' else
                    state if ACTION == 'reboot' else 'V3_BASELINE')
  if state != expected_state:
    raise RuntimeError('Unexpected state for ' + ACTION)
  if ACTION in ('install', 'rollback'):
    for name in CONFIG['changed']:
      for prefix, hashes in (('new-', CONFIG['after_sha256']), ('old-', CONFIG['before_sha256'])):
        p = stage / (prefix + name)
        target = str(vw / name)
        if digest(p) != hashes[target]:
          raise RuntimeError('Staging hash mismatch: ' + p.name)
        compile(p.read_bytes(), name, 'exec')
    # End speed/test mode and drain the active trace before the reboot.
    with urlopen(Request('http://127.0.0.1:8766/mode', data=b'{"mode":"base"}',
                 headers={'Content-Type': 'application/json'}), timeout=3) as response:
      if json.loads(response.read())['mode'] != 'base':
        raise RuntimeError('Could not confirm default base mode')
    with urlopen(Request('http://127.0.0.1:8766/shutdown', data=b'{}',
                 headers={'Content-Type': 'application/json'}), timeout=8) as response:
      if response.status != 200:
        raise RuntimeError('Could not cleanly stop logger/backend')
    # Preserve original files once, never overwrite a recovery snapshot.
    for name in CONFIG['changed']:
      p = vw / name
      snapshot = stage / ('snapshot-' + name)
      if not snapshot.exists():
        atomic(p, snapshot)
      if digest(snapshot) != CONFIG['before_sha256'][str(p)]:
        raise RuntimeError('Recovery snapshot does not match original V3')
    prefix = 'new-' if ACTION == 'install' else 'old-'
    expected = CONFIG['after_sha256'] if ACTION == 'install' else CONFIG['before_sha256']
    try:
      for name in CONFIG['changed']:
        atomic(stage / (prefix + name), vw / name)
      if {name: digest(pathlib.Path(name)) for name in expected} != expected:
        raise RuntimeError('Installed hash verification failed')
      if ACTION == 'install':
        from selfdrive.car.volkswagen.hca_timer_reset import HcaTimerReset, VERSION
        from selfdrive.car.volkswagen.pq46_runtime import Runtime, model_features
        from selfdrive.car.volkswagen.carcontroller import CarController
        from common.params import Params
        from cereal import car
        cp = car.CarParams.from_bytes(Params().get('CarParams'))
        from selfdrive.car.volkswagen.values import DBC
        controller = CarController(DBC[cp.carFingerprint]['pt'], cp, None)
        now = controller.pq_runtime.update(0)
        if VERSION != 'hca-r1' or cp.openpilotLongitudinalControl:
          raise RuntimeError('Unexpected smoke identity or longitudinal mode')
        # Exercise the actual Cap'n Proto model schema, without sending CAN.
        sm = controller.pq_runtime.sm
        for _ in range(20):
          sm.update(100)
          if sm.updated['modelV2']:
            break
        features = model_features(sm['modelV2'], 0)
        if features['reason'] == 'model_schema_unavailable':
          raise RuntimeError('Device model schema incompatible')
        print(json.dumps({'smoke': True, 'version': VERSION, 'car': cp.carFingerprint,
                          'geometry': features, 'cruise_mode': controller.pq_cruise.mode,
                          'CAN_transmitted_by_smoke': False}), flush=True)
    except Exception:
      if ACTION == 'install':
        for name in CONFIG['changed']:
          atomic(stage / ('old-' + name), vw / name)
      raise
    print(json.dumps({'result': ACTION, 'reboot_required': True}), flush=True)
  elif ACTION == 'reboot':
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = ''
    subprocess.Popen(['/system/bin/reboot'], env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    print(json.dumps({'reboot_requested': True}), flush=True)
  elif ACTION != 'validate':
    raise RuntimeError('Unknown action')
'''


def remote_action(args, manifest, action):
  guard = (ROOT / 'tools/c2_parked_guard.py').read_text(encoding='utf-8')
  code = 'CONFIG=%r\nACTION=%r\nPARKED_IGNITION=%r\n' % (manifest, action, args.parked_ignition)
  result = subprocess.run(ssh_prefix(args) + ['cd /data/openpilot && python3 -'],
                          input=code + guard + '\n' + REMOTE, text=True, encoding='utf-8',
                          capture_output=True, timeout=45)
  print(result.stdout, end='', flush=True)
  if result.returncode:
    raise RuntimeError(result.stderr.strip() or 'SSH action failed')


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--ip', required=True)
  parser.add_argument('--port', type=int, default=8022)
  parser.add_argument('--user', default='root')
  parser.add_argument('--identity', type=Path, default=Path.home() / '.ssh/vwopenploot_c2_id_rsa')
  parser.add_argument('--known-hosts', type=Path, default=Path.home() / '.ssh/known_hosts_vwopenploot_c2')
  parser.add_argument('--action', choices=('status', 'validate', 'install', 'rollback', 'reboot'), default='status')
  parser.add_argument('--parked-ignition', action='store_true')
  args = parser.parse_args()
  manifest = json.loads((PACKAGE / 'manifest.json').read_text(encoding='utf-8'))
  if args.action not in ('install', 'rollback'):
    remote_action(args, manifest, args.action)
    return
  remote_action(args, manifest, 'validate' if args.action == 'install' else 'status')
  subprocess.run(ssh_prefix(args) + ['mkdir -p ' + STAGE + ' && chmod 700 ' + STAGE], check=True, timeout=20)
  scp = ['scp', '-q', '-O', '-P', str(args.port), '-i', str(args.identity),
         '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
         '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(args.known_hosts)]
  for name in manifest['changed']:
    for folder, prefix, hashes in (('deploy', 'new-', manifest['after_sha256']),
                                   ('rollback', 'old-', manifest['before_sha256'])):
      source = PACKAGE / folder / name
      if hashlib.sha256(source.read_bytes()).hexdigest() != hashes['/data/openpilot/selfdrive/car/volkswagen/' + name]:
        raise RuntimeError('Local payload hash mismatch: ' + str(source))
      subprocess.run(scp + [str(source), args.user + '@' + args.ip + ':' + STAGE + '/' + prefix + name],
                     check=True, timeout=30)
  remote_action(args, manifest, args.action)
  remote_action(args, manifest, 'status')


if __name__ == '__main__':
  try:
    main()
  except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)
