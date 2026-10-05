"""Install/rollback only the read-only Android monitor; never replace control files."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT/'candidate/device-a6eed9e-hca-monitor'
REMOTE = r'''
import hashlib, json, os, pathlib, subprocess, time
from urllib.request import urlopen
stage = pathlib.Path('/data/pq46_hca_monitor_staging')
env = os.environ.copy()
env['LD_LIBRARY_PATH'] = ''
def native(*args):
    return subprocess.run(args, env=env, text=True, capture_output=True, check=True, timeout=90).stdout
def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def controls():
    return {path:digest(path) for path in CONFIG['preserved_control_sha256']}
def installed_apk():
    lines = native('/system/bin/pm', 'path', 'nl.vwopenploot.probe').splitlines()
    if len(lines) != 1 or not lines[0].startswith('package:/data/app/'):
        raise RuntimeError('Unexpected Android package path')
    return pathlib.Path(lines[0][len('package:'):])
def install(path):
    native('/system/bin/am', 'force-stop', 'nl.vwopenploot.probe')
    inbox = pathlib.Path('/data/local/tmp/pq46-monitor-install.apk')
    inbox.write_bytes(path.read_bytes())
    os.chmod(str(inbox), 0o644)
    try:
        if digest(inbox) != digest(path): raise RuntimeError('APK inbox hash mismatch')
        result = native('/system/bin/pm', 'install', '-r', '-d', str(inbox))
        if 'Success' not in result: raise RuntimeError('APK installer did not confirm success')
    finally:
        inbox.unlink(missing_ok=True)
def launch():
    native('/system/bin/am', 'start', '-n', 'nl.vwopenploot.probe/.OverlayActivity')
before = controls()
if before != CONFIG['preserved_control_sha256']:
    raise RuntimeError('Control files differ from the pinned r2 baseline; no installation')
if subprocess.check_output(['git','-C','/data/openpilot','rev-parse','HEAD'],text=True).strip() != CONFIG['base_commit']:
    raise RuntimeError('Unknown device source baseline')
with urlopen('http://127.0.0.1:8766/status', timeout=2) as reply: status = json.load(reply)
if status.get('mode') != 'base': raise RuntimeError('Expected base mode; monitor does not change modes')
require_parked_ignition()
current_path = installed_apk()
current = digest(current_path)
stage.mkdir(mode=0o700, parents=True, exist_ok=True)
old = stage/'original-overlay.apk'
new = stage/'monitor-overlay.apk'
if digest(new) != CONFIG['monitor_apk_sha256']: raise RuntimeError('Uploaded monitor APK differs')
if current == CONFIG['previous_apk_sha256']:
    if old.exists() and digest(old) != current: raise RuntimeError('Existing rollback APK differs')
    if not old.exists(): old.write_bytes(current_path.read_bytes())
elif current != CONFIG['monitor_apk_sha256']:
    raise RuntimeError('Installed APK differs from both pinned versions')
if not old.exists() or digest(old) != CONFIG['previous_apk_sha256']:
    raise RuntimeError('Valid original APK rollback missing')
target = old if ACTION == 'rollback' else new
target_hash = CONFIG['previous_apk_sha256'] if ACTION == 'rollback' else CONFIG['monitor_apk_sha256']
restore = new if ACTION == 'rollback' else old
try:
    require_parked_ignition()
    install(target)
    if digest(installed_apk()) != target_hash: raise RuntimeError('Installed APK hash mismatch')
    after = controls()
    if after != before: raise RuntimeError('Control files changed concurrently; stop and inspect')
    launch()
except Exception:
    install(restore)
    launch()
    raise
report = {'action':ACTION,'package':'nl.vwopenploot.probe','version':'0.5-monitor' if ACTION=='install' else '0.3',
          'apk_before_sha256':current,'apk_after_sha256':digest(installed_apk()),
          'control_hashes_before':before,'control_hashes_after':after,'control_files_unchanged':before==after,
          'mode_before':status.get('mode'),'remote_rollback_apk':str(old),
          'scope':'Android read-only monitor APK only; no reboot, control changes, mode writes or CAN commands',
          'boot_s':time.monotonic()}
(stage/'last-result.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
'''


def prefix(args, scp=False):
  return ['scp' if scp else 'ssh', '-P' if scp else '-p', str(args.port), '-i', str(args.identity),
          '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6',
          '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile='+str(args.known_hosts)]


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--ip', required=True)
  parser.add_argument('--port', type=int, default=8022)
  parser.add_argument('--identity', type=Path, default=Path.home()/'.ssh/vwopenploot_c2_id_rsa')
  parser.add_argument('--known-hosts', type=Path, default=Path.home()/'.ssh/known_hosts_vwopenploot_c2')
  parser.add_argument('--action', choices=('install','rollback'), default='install')
  args = parser.parse_args()
  ipaddress.ip_address(args.ip)
  config = json.loads((PACKAGE/'manifest.json').read_text(encoding='utf-8'))
  apk = PACKAGE/'deploy/overlay.apk'
  if hashlib.sha256(apk.read_bytes()).hexdigest() != config['monitor_apk_sha256']:
    raise RuntimeError('Local APK differs from its manifest')
  host = 'root@'+args.ip
  subprocess.run(prefix(args)+[host, 'mkdir -p /data/pq46_hca_monitor_staging'], check=True, timeout=15)
  subprocess.run(prefix(args, scp=True)+['-q','-O', str(apk),host+':/data/pq46_hca_monitor_staging/monitor-overlay.apk'],
                 check=True,timeout=30)
  guard = (ROOT/'tools/c2_parked_guard.py').read_text(encoding='utf-8')
  code = 'CONFIG = '+repr(config)+'\nACTION = '+repr(args.action)+'\n'+guard+'\n'+REMOTE
  result = subprocess.run(prefix(args)+[host,'cd /data/openpilot && python3 -'],input=code,
                          text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=150)
  backup = ROOT/'device-backups/hca-monitor-install-20261003'
  backup.mkdir(parents=True,exist_ok=True)
  (backup/(args.action+'-stdout.txt')).write_text(result.stdout,encoding='utf-8')
  (backup/(args.action+'-stderr.txt')).write_text(result.stderr,encoding='utf-8')
  result.check_returncode()
  report = json.loads(result.stdout.strip().splitlines()[-1])
  (backup/(args.action+'-result.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  subprocess.run(prefix(args,scp=True)+['-q','-O',host+':/data/pq46_hca_monitor_staging/original-overlay.apk',str(backup/'original-overlay.apk')],
                 check=True,timeout=30)
  if hashlib.sha256((backup/'original-overlay.apk').read_bytes()).hexdigest() != config['previous_apk_sha256']:
    raise RuntimeError('Downloaded original APK differs')
  print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
  try:
    main()
  except (OSError,RuntimeError,subprocess.SubprocessError) as error:
    print('ERROR: '+str(error), file=sys.stderr)
    sys.exit(1)
