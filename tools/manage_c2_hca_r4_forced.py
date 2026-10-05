"""Pinned parked-only upgrade to hca-r4-forced (350 s prompt + 355 s forced pause).

Default action is read-only status. install/rollback are explicit, verify the
currently deployed hca-r3-staged hashes and the installed overlay APK before any
mutation, and restore both on failure. The forced fallback never soft-disables,
so no reboot-time event state is touched here.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from manage_c2_v3_package import ssh_prefix, REMOTE as V3_REMOTE

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'candidate/device-a6eed9e-v3-hca-r4-forced'
STAGE = '/data/pq46_hca_r4_forced_staging'

_app_install = next(n for n in ast.parse(V3_REMOTE).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'app_install')
HELPERS = r'''
def destination(name):
  return pathlib.Path(CONFIG['changed_targets'][name])

def current_apk_hash():
  env = os.environ.copy()
  env['LD_LIBRARY_PATH'] = ''
  result = subprocess.run(['/system/bin/pm', 'path', 'nl.vwopenploot.probe'], env=env,
                          capture_output=True, text=True, timeout=15)
  paths = [s[8:] for s in result.stdout.splitlines() if s.startswith('package:')]
  if result.returncode or len(paths) != 1:
    raise RuntimeError('Cannot identify installed overlay APK')
  return digest(pathlib.Path(paths[0]))

''' + ast.unparse(_app_install) + '\n'

REMOTE = r'''
import hashlib, importlib.util, json, os, pathlib, subprocess, tempfile, time
from urllib.request import Request, urlopen
stage = pathlib.Path('<STAGE>')
base = pathlib.Path('/data/openpilot')
params = pathlib.Path('/data/params/d_tmp')

def digest(path):
  return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def parameter(name):
  p = params / name
  return p.read_text(errors='replace').strip() if p.is_file() else None

def atomic(source, destination):
  with tempfile.NamedTemporaryFile(dir=str(destination.parent), prefix='.hca-r4-', delete=False) as output:
    temp = pathlib.Path(output.name)
    output.write(source.read_bytes())
    output.flush()
    os.fsync(output.fileno())
  try:
    os.chmod(str(temp), 0o644)
    os.replace(str(temp), str(destination))
  finally:
    temp.unlink(missing_ok=True)

<HELPERS>
current = {name: digest(pathlib.Path(name)) for name in CONFIG['before_sha256']}
apk_current = current_apk_hash()
state = ('HCA_R3_STAGED_BASELINE' if current == CONFIG['before_sha256'] and apk_current == CONFIG['apk_sha256']['before'] else
         'HCA_R4_FORCED_PRESENT' if current == CONFIG['after_sha256'] and apk_current == CONFIG['apk_sha256']['after'] else 'FILE_MISMATCH')
print(json.dumps({'state': state, 'files': current, 'apk_sha256': apk_current,
                  'IsOffroad': parameter('IsOffroad'), 'DisableUpdates': parameter('DisableUpdates'),
                  'boot_s': time.monotonic()}), flush=True)
if ACTION == 'status':
  pass
else:
  if state == 'FILE_MISMATCH':
    raise RuntimeError('Device differs from pinned r3/r4 files')
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
  expected_state = ('HCA_R4_FORCED_PRESENT' if ACTION == 'rollback' else
                    state if ACTION == 'reboot' else 'HCA_R3_STAGED_BASELINE')
  if state != expected_state:
    raise RuntimeError('Unexpected state for ' + ACTION)
  if ACTION in ('install', 'rollback'):
    for name in CONFIG['changed']:
      for prefix, hashes in (('new-', CONFIG['after_sha256']), ('old-', CONFIG['before_sha256'])):
        p = stage / (prefix + name)
        if digest(p) != hashes[str(destination(name))]:
          raise RuntimeError('Staging hash mismatch: ' + p.name)
        compile(p.read_bytes(), name, 'exec')
    for prefix, value in (('new-', CONFIG['apk_sha256']['after']), ('old-', CONFIG['apk_sha256']['before'])):
      if digest(stage / (prefix + 'overlay.apk')) != value:
        raise RuntimeError('Staging APK hash mismatch')
    # End speed/test mode and drain the active trace before the reboot.
    with urlopen(Request('http://127.0.0.1:8766/mode', data=b'{"mode":"base"}',
                 headers={'Content-Type': 'application/json'}), timeout=3) as response:
      if json.loads(response.read())['mode'] != 'base':
        raise RuntimeError('Could not confirm default base mode')
    with urlopen(Request('http://127.0.0.1:8766/shutdown', data=b'{}',
                 headers={'Content-Type': 'application/json'}), timeout=8) as response:
      if response.status != 200:
        raise RuntimeError('Could not cleanly stop logger/backend')
    # Preserve the deployed r3 files once; never overwrite a recovery snapshot.
    for name in CONFIG['changed']:
      p = destination(name)
      snapshot = stage / ('snapshot-' + name)
      if not snapshot.exists():
        atomic(p, snapshot)
      if digest(snapshot) != CONFIG['before_sha256'][str(p)]:
        raise RuntimeError('Recovery snapshot does not match deployed r3')
    prefix = 'new-' if ACTION == 'install' else 'old-'
    expected = CONFIG['after_sha256'] if ACTION == 'install' else CONFIG['before_sha256']
    try:
      for name in CONFIG['changed']:
        atomic(stage / (prefix + name), destination(name))
      app_install(stage / (prefix + 'overlay.apk'))
      if current_apk_hash() != CONFIG['apk_sha256']['after' if ACTION == 'install' else 'before']:
        raise RuntimeError('Installed APK verification failed')
      if {name: digest(pathlib.Path(name)) for name in expected} != expected:
        raise RuntimeError('Installed hash verification failed')
      if ACTION == 'install':
        from selfdrive.car.volkswagen.hca_timer_reset import HcaTimerReset, VERSION
        from selfdrive.car.volkswagen.carcontroller import CarController
        from common.params import Params
        from cereal import car
        cp = car.CarParams.from_bytes(Params().get('CarParams'))
        from selfdrive.car.volkswagen.values import DBC
        controller = CarController(DBC[cp.carFingerprint]['pt'], cp, None)
        now = controller.pq_runtime.update(0)
        timer = controller.pq_hca_timer_reset
        if (VERSION != 'hca-r4-forced' or cp.openpilotLongitudinalControl or
            timer.seek != 9000 or timer.prompt != 17500 or timer.forced != 17750 or
            timer.required != 55 or timer.backstop != 20000):
          raise RuntimeError('Unexpected smoke identity or staging windows')
        # Exercise the real deployed scheduler in memory; this sends no CAN.
        prompt = HcaTimerReset(quiet_s=.02)
        prompt.elapsed = round(349.98 * 50)
        prompt.update(True, 40, raw_torque=40, window_ok=True, continue_ok=True,
                      delayed_ok=True, notice_ready=True)
        if prompt.phase != 'forced_prompt' or prompt.takeover_required:
          raise RuntimeError('350 s prompt must not request a soft disable')
        forced = HcaTimerReset(quiet_s=.02)
        forced.elapsed = round(354.98 * 50)
        out = forced.update(True, 150, raw_torque=150, window_ok=False, driver_input=True)
        if forced.phase != 'forced_standby' or out[1]:
          raise RuntimeError('355 s forced fallback did not engage')
        print(json.dumps({'smoke': True, 'version': VERSION, 'car': cp.carFingerprint,
                          'timer': timer.status(), 'prompt_probe': prompt.phase,
                          'forced_probe': forced.phase, 'cruise_mode': controller.pq_cruise.mode,
                          'CAN_transmitted_by_smoke': False}), flush=True)
    except Exception as original:
      recovery_prefix = 'old-' if ACTION == 'install' else 'new-'
      try:
        for name in CONFIG['changed']:
          atomic(stage / (recovery_prefix + name), destination(name))
        app_install(stage / (recovery_prefix + 'overlay.apk'))
      except Exception as recovery:
        raise RuntimeError('Transaction failed and recovery failed: %s; %s' % (original, recovery))
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

REMOTE = REMOTE.replace('<STAGE>', STAGE).replace('<HELPERS>', HELPERS)
compile(REMOTE, 'r4_remote', 'exec')


def remote_action(args, manifest, action):
  guard = (ROOT / 'tools/c2_parked_guard.py').read_text(encoding='utf-8')
  code = 'CONFIG=%r\nACTION=%r\nPARKED_IGNITION=%r\n' % (manifest, action, args.parked_ignition)
  result = subprocess.run(ssh_prefix(args) + ['cd /data/openpilot && python3 -'],
                          input=code + guard + '\n' + REMOTE, text=True, encoding='utf-8',
                          capture_output=True, timeout=180)
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
  for name, target in manifest['changed_targets'].items():
    for folder, prefix, key in (('deploy', 'new-', 'after_sha256'), ('rollback', 'old-', 'before_sha256')):
      source = PACKAGE / folder / name
      if hashlib.sha256(source.read_bytes()).hexdigest() != manifest[key][target]:
        raise RuntimeError('Local payload hash mismatch: ' + str(source))
      subprocess.run(scp + [str(source), args.user + '@' + args.ip + ':' + STAGE + '/' + prefix + name],
                     check=True, timeout=30)
  for folder, prefix, key in (('deploy', 'new-', 'after'), ('rollback', 'old-', 'before')):
    source = PACKAGE / folder / 'overlay.apk'
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest['apk_sha256'][key]:
      raise RuntimeError('Local payload hash mismatch: ' + str(source))
    subprocess.run(scp + [str(source), args.user + '@' + args.ip + ':' + STAGE + '/' + prefix + 'overlay.apk'],
                   check=True, timeout=30)
  remote_action(args, manifest, args.action)
  remote_action(args, manifest, 'status')


if __name__ == '__main__':
  try:
    main()
  except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)
