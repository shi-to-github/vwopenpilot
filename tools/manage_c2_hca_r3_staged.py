"""Pinned r2-to-r3 staged scheduler/APK install. Default is read-only status."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from manage_c2_v3_package import ssh_prefix, REMOTE as V3_REMOTE
from manage_c2_hca_r2_entry import REMOTE as R2_REMOTE

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'candidate/device-a6eed9e-v3-hca-r3-staged'
STAGE='/data/pq46_hca_r3_staged_staging'
app_node=next(n for n in ast.parse(V3_REMOTE).body if isinstance(n,ast.FunctionDef) and n.name=='app_install')
HELPERS=r'''
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

'''+ast.unparse(app_node)+'\n'
REMOTE=R2_REMOTE.replace('/data/pq46_hca_r2_entry_staging',STAGE)
REMOTE=REMOTE.replace('HCA_R1_DIAG1_BASELINE','HCA_R2_ENTRY_BASELINE').replace('HCA_R2_ENTRY_PRESENT','HCA_R3_STAGED_PRESENT')
REMOTE=REMOTE.replace('current = {name:',HELPERS+'\napk_current = current_apk_hash()\ncurrent = {name:',1)
REMOTE=REMOTE.replace("current == CONFIG['before_sha256']", "current == CONFIG['before_sha256'] and apk_current == CONFIG['apk_sha256']['before']",1)
REMOTE=REMOTE.replace("current == CONFIG['after_sha256']", "current == CONFIG['after_sha256'] and apk_current == CONFIG['apk_sha256']['after']",1)
REMOTE=REMOTE.replace("'state': state, 'files': current,", "'state': state, 'files': current, 'apk_sha256': apk_current,")
REMOTE=REMOTE.replace('str(vw / name)','str(destination(name))').replace('p = vw / name','p = destination(name)').replace(', vw / name)',', destination(name))')
REMOTE=REMOTE.replace('    # End speed/test mode', '''    for prefix, value in (('new-', CONFIG['apk_sha256']['after']), ('old-', CONFIG['apk_sha256']['before'])):
      if digest(stage / (prefix + 'overlay.apk')) != value:
        raise RuntimeError('Staging APK hash mismatch')
    # End speed/test mode''')
REMOTE=REMOTE.replace('      if {name: digest(pathlib.Path(name)) for name in expected} != expected:',
                      "      app_install(stage / (prefix + 'overlay.apk'))\n      if current_apk_hash() != CONFIG['apk_sha256']['after' if ACTION == 'install' else 'before']:\n        raise RuntimeError('Installed APK verification failed')\n      if {name: digest(pathlib.Path(name)) for name in expected} != expected:")
REMOTE=REMOTE.replace("VERSION != 'hca-r2-entry'", "VERSION != 'hca-r3-staged'")
REMOTE=REMOTE.replace('controller.pq_hca_timer_reset.seek != 7500', 'controller.pq_hca_timer_reset.seek != 9000')
REMOTE=REMOTE.replace('controller.pq_hca_timer_reset.entry_window_frames != 20',
                      'controller.pq_hca_timer_reset.required != 55 or controller.pq_hca_timer_reset.warn != 15000')
REMOTE=REMOTE.replace("    except Exception:\n      if ACTION == 'install':\n        for name in CONFIG['changed']:\n          atomic(stage / ('old-' + name), destination(name))\n      raise", """    except Exception as original:
      recovery_prefix = 'old-' if ACTION == 'install' else 'new-'
      try:
        for name in CONFIG['changed']:
          atomic(stage / (recovery_prefix + name), destination(name))
        app_install(stage / (recovery_prefix + 'overlay.apk'))
      except Exception as recovery:
        raise RuntimeError('Transaction failed and recovery failed: %s; %s' % (original, recovery))
      raise""")
compile(REMOTE,'r3_remote','exec')


def remote_action(args,manifest,action):
  guard=(ROOT/'tools/c2_parked_guard.py').read_text(encoding='utf-8')
  code='CONFIG=%r\nACTION=%r\nPARKED_IGNITION=%r\n'%(manifest,action,args.parked_ignition)
  result=subprocess.run(ssh_prefix(args)+['cd /data/openpilot && python3 -'],input=code+guard+'\n'+REMOTE,
                        text=True,encoding='utf-8',capture_output=True,timeout=180)
  print(result.stdout,end='',flush=True)
  if result.returncode:raise RuntimeError(result.stderr.strip() or 'SSH action failed')


def main():
  p=argparse.ArgumentParser(description=__doc__)
  p.add_argument('--ip',required=True);p.add_argument('--port',type=int,default=8022)
  p.add_argument('--user',default='root')
  p.add_argument('--identity',type=Path,default=Path.home()/'.ssh/vwopenploot_c2_id_rsa')
  p.add_argument('--known-hosts',type=Path,default=Path.home()/'.ssh/known_hosts_vwopenploot_c2')
  p.add_argument('--action',choices=('status','validate','install','rollback','reboot'),default='status')
  p.add_argument('--parked-ignition',action='store_true')
  args=p.parse_args();manifest=json.loads((PACKAGE/'manifest.json').read_text(encoding='utf-8'))
  if args.action not in ('install','rollback'):
    remote_action(args,manifest,args.action);return
  remote_action(args,manifest,'validate' if args.action=='install' else 'status')
  subprocess.run(ssh_prefix(args)+['mkdir -p '+STAGE+' && chmod 700 '+STAGE],check=True,timeout=20)
  scp=['scp','-q','-O','-P',str(args.port),'-i',str(args.identity),'-o','IdentitiesOnly=yes','-o','BatchMode=yes',
       '-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(args.known_hosts)]
  for sub,prefix,key in (('deploy','new-','after_sha256'),('rollback','old-','before_sha256')):
    for name,target in manifest['changed_targets'].items():
      path=PACKAGE/sub/name
      if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest[key][target]:raise RuntimeError('Local file hash mismatch: '+name)
      subprocess.run(scp+[str(path),args.user+'@'+args.ip+':'+STAGE+'/'+prefix+name],check=True,timeout=30)
    path=PACKAGE/sub/'overlay.apk'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['apk_sha256']['after' if sub=='deploy' else 'before']:
      raise RuntimeError('Local APK hash mismatch')
    subprocess.run(scp+[str(path),args.user+'@'+args.ip+':'+STAGE+'/'+prefix+'overlay.apk'],check=True,timeout=30)
  remote_action(args,manifest,args.action)
  remote_action(args,manifest,'status')


if __name__=='__main__':
  try:main()
  except (OSError,RuntimeError,subprocess.SubprocessError,ValueError) as error:
    print(str(error),file=sys.stderr);sys.exit(1)
