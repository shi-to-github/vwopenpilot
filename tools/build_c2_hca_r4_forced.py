"""Package the r4 forced-fallback controls, overlay APK and exact r3 rollback."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'candidate/device-a6eed9e-v3-hca-r4-forced'
R3=ROOT/'candidate/device-a6eed9e-v3-hca-r3-staged'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
  base=json.loads((R3/'manifest.json').read_text())
  # The pinned rollback is exactly what is deployed right now: hca-r3-staged.
  before=base['after_sha256'].copy();after=before.copy()
  changed={'hca_timer_reset.py':'/data/openpilot/selfdrive/car/volkswagen/hca_timer_reset.py',
           'v3_server.py':'/data/pq46/v3_server.py'}
  for name,target in changed.items():
    original=R3/'deploy'/name
    if digest(original)!=before[target]:raise RuntimeError('Pinned r3 original mismatch: '+name)
    shutil.copyfile(original,PACKAGE/'rollback'/name)
    compile((PACKAGE/'deploy'/name).read_bytes(),name,'exec')
    after[target]=digest(PACKAGE/'deploy'/name)
  shutil.copyfile(R3/'deploy/overlay.apk',PACKAGE/'rollback/overlay.apk')
  shutil.copyfile(PACKAGE/'overlay/build/pq46-probe-overlay.apk',PACKAGE/'deploy/overlay.apk')
  manifest={'version':'hca-r4-forced','device_branch':base['device_branch'],'base_commit':base['base_commit'],
            'changed':list(changed),'changed_targets':changed,'before_sha256':before,'after_sha256':after,
            'apk_sha256':{'before':digest(PACKAGE/'rollback/overlay.apk'),
                          'after':digest(PACKAGE/'deploy/overlay.apk')},
            'parameters':{'normal_until_s':180,'notice_from_s':300,'prompt_at_s':350,
                          'forced_pause_at_s':355,'backstop_at_s':400,'unconditional_pause':True,
                          'forced_pause_abort_gates':False,'soft_disable_at_prompt':False,
                          'assumed_hardware_limit_s':360,'standby_s':1.1,'standby_frames':55,
                          'scheduled_notice_s':3,'prediction_margin_s':.2,
                          'single_90_request_abort':False,'sustained_saturation_threshold':270,
                          'saturation_duration_s':.2,'opportunistic_counters_separate':True},
            'deployment_status':'stable-1: installed and reboot verified 2026-10-03; 3 h 34 m road drive with zero assist loss',
            'stable_tag':'stable-1-hca-r4-forced',
            'road_result':('2026-10-03 approx 19:16-22:50, about 3 h 34 m and 60 reset cycles; opportunistic resets '
                           'typically 180-220 s, occasionally 250-300+ s, never past 300 s; zero assist disconnection; '
                           '355 s forced fallback never exercised on road. Driver perception only, raw trace not retrieved.'),
            'verify_note':'1.1 s standby effective for this 5N1/0503 rack per driver report; no raw 978 frames collected',
            'longitudinal_default':'base/off',
            'verification_record':'docs/HCA_R4_FORCED_DEPLOYMENT_20261003.md',
            'road_review':'docs/R4_ROAD_REVIEW_20261003.md'}
  (PACKAGE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
  out=ROOT/'artifacts/pq46-c2-hca-r4-forced.zip'
  with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    for path in sorted(PACKAGE.rglob('*')):
      if path.is_file() and not any(p in ('build','__pycache__') for p in path.parts):z.write(path,path.relative_to(ROOT).as_posix())
    for name in ('manage_c2_hca_r4_forced.py','manage_c2_v3_package.py','c2_parked_guard.py',
                 'build_c2_hca_r4_forced.py','build_c2_probe_overlay.py','review_hca_r4_logs.py'):
      path=ROOT/'tools'/name;z.write(path,path.relative_to(ROOT).as_posix())
  out.with_suffix('.zip.sha256').write_text(digest(out)+'  '+out.name+'\n')
  print(json.dumps({'archive':str(out),'sha256':digest(out),'changed':list(changed),
                    'rollback':base['version'],'apk_after':manifest['apk_sha256']['after'],
                    'device_contacted':False}))


if __name__=='__main__':main()
