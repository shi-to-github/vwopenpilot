"""Package local r3 controls, large overlay and exact deployed-r2 rollback."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'candidate/device-a6eed9e-v3-hca-r3-staged'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
  base=json.loads((ROOT/'candidate/device-a6eed9e-v3-hca-r2-entry/manifest.json').read_text())
  before=base['after_sha256'].copy();after=before.copy()
  originals={'hca_timer_reset.py':'device-a6eed9e-v3-hca-r2-entry/deploy/hca_timer_reset.py',
             'carcontroller.py':'device-a6eed9e-v3-hca-r1/deploy/carcontroller.py',
             'pq46_runtime.py':'device-a6eed9e-v3-hca-r1/deploy/pq46_runtime.py',
             'v3_server.py':'device-a6eed9e-v3/diagnostics/v3_server.py'}
  targets={}
  for name,source in originals.items():
    target=('/data/pq46/' if name=='v3_server.py' else '/data/openpilot/selfdrive/car/volkswagen/')+name
    original=ROOT/'candidate'/source
    if digest(original)!=before[target]:raise RuntimeError('Pinned original mismatch: '+name)
    shutil.copyfile(original,PACKAGE/'rollback'/name)
    compile((PACKAGE/'deploy'/name).read_bytes(),name,'exec')
    after[target]=digest(PACKAGE/'deploy'/name);targets[name]=target
  old_apk=ROOT/'candidate/device-a6eed9e-hca-monitor/deploy/overlay.apk'
  old_meta=json.loads((ROOT/'candidate/device-a6eed9e-hca-monitor/manifest.json').read_text())
  if digest(old_apk)!=old_meta['monitor_apk_sha256']:raise RuntimeError('Pinned monitor APK mismatch')
  shutil.copyfile(old_apk,PACKAGE/'rollback/overlay.apk')
  shutil.copyfile(PACKAGE/'overlay/build/pq46-probe-overlay.apk',PACKAGE/'deploy/overlay.apk')
  manifest={'version':'hca-r3-staged','device_branch':base['device_branch'],'base_commit':base['base_commit'],
            'changed':list(originals),'changed_targets':targets,'before_sha256':before,'after_sha256':after,
            'apk_sha256':{'before':digest(PACKAGE/'rollback/overlay.apk'),'after':digest(PACKAGE/'deploy/overlay.apk')},
            'parameters':{'normal_until_s':180,'notice_from_s':300,'takeover_at_s':350,
                          'unconditional_pause':False,'assumed_hardware_limit_s':360,'standby_s':1.1,
                          'standby_frames':55,'scheduled_notice_s':3,
                          'prediction_margin_s':.2,'single_90_request_abort':False,
                          'sustained_saturation_threshold':270,'saturation_duration_s':.2},
            'deployment_status':'local only; not installed','longitudinal_default':'base/off'}
  (PACKAGE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
  out=ROOT/'artifacts/pq46-c2-hca-r3-staged.zip'
  with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    for path in sorted(PACKAGE.rglob('*')):
      if path.is_file() and not any(p in ('build','__pycache__') for p in path.parts):z.write(path,path.relative_to(ROOT).as_posix())
    for name in ('manage_c2_hca_r3_staged.py','manage_c2_hca_r2_entry.py','manage_c2_v3_package.py',
                 'c2_parked_guard.py','build_c2_hca_r3_staged.py'):
      path=ROOT/'tools'/name;z.write(path,path.relative_to(ROOT).as_posix())
  out.with_suffix('.zip.sha256').write_text(digest(out)+'  '+out.name+'\n')
  print(json.dumps({'archive':str(out),'sha256':digest(out),'changed':list(originals),'device_contacted':False}))


if __name__=='__main__':main()
