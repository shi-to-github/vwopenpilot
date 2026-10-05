"""Build a local 1.1-second candidate from the pinned deployed r2 package."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT/'candidate/device-a6eed9e-v3-hca-r2-1100ms'
BASE = ROOT/'candidate/device-a6eed9e-v3-hca-r2-entry'


def replace_once(text, old, new):
  if text.count(old) != 1:
    raise ValueError('Expected one source anchor: '+old)
  return text.replace(old,new)


def build():
  originals = {
    'hca_timer_reset.py': (BASE/'deploy/hca_timer_reset.py').read_bytes(),
    'carcontroller.py': (ROOT/'candidate/device-a6eed9e-v3-hca-r1/deploy/carcontroller.py').read_bytes(),
    'pq46_runtime.py': (ROOT/'candidate/device-a6eed9e-v3-hca-r1/deploy/pq46_runtime.py').read_bytes(),
  }
  baseline = json.loads((BASE/'manifest.json').read_text())
  before = baseline['after_sha256'].copy()
  after = before.copy()
  for sub in ('deploy','rollback'):(PACKAGE/sub).mkdir(parents=True,exist_ok=True)
  for name,data in originals.items():
    remote='/data/openpilot/selfdrive/car/volkswagen/'+name
    assert hashlib.sha256(data).hexdigest()==before[remote], name
    text=data.decode('utf-8')
    if name=='hca_timer_reset.py':
      text=replace_once(text,"VERSION = 'hca-r2-entry'","VERSION = 'hca-r2-1100ms'")
      text=replace_once(text,'seek_after_s=150, standby_s=2,','seek_after_s=150, standby_s=1.1,')
    elif name=='carcontroller.py':
      text=replace_once(text,'self.pq_hca_timer_reset.standby else 2',
                        'self.pq_hca_timer_reset.standby else (self.pq_hca_timer_reset.required /\n                 self.pq_hca_timer_reset.hz if self.pq_hca_timer_reset is not None else 2)')
    else:
      text=replace_once(text,"STATUS = ROOT / 'v3_status.json'",
                        "STATUS = ROOT / 'v3_status.json'\nSTANDBY_S = 1.1\nPREDICTION_MARGIN_S = .2\nPREDICTION_HORIZON_S = STANDBY_S + PREDICTION_MARGIN_S")
      text=replace_once(text,'max(times) < 2.5','max(times) < PREDICTION_HORIZON_S')
      text=replace_once(text,'if 0 <= t <= 2.5','if 0 <= t <= PREDICTION_HORIZON_S')
      text=replace_once(text,'    if not future:\n',
                        '    # Include the exact horizon boundary between model samples.\n'
                        '    for i, (a, b) in enumerate(zip(times, times[1:])):\n'
                        '      if a < PREDICTION_HORIZON_S < b:\n'
                        '        fraction = (PREDICTION_HORIZON_S - a) / (b - a)\n'
                        '        boundary_yaw = yaw[i] + fraction * (yaw[i + 1] - yaw[i])\n'
                        '        future.append(abs(boundary_yaw) * max(speed, 1))\n'
                        '        break\n'
                        '    if not future:\n')
      text=replace_once(text,'motion_gate(self.geometry, self.center_rate, 2)',
                        'motion_gate(self.geometry, self.center_rate, STANDBY_S)')
      text=replace_once(text,'def update(self, speed, remaining_s=2):',
                        'def update(self, speed, remaining_s=STANDBY_S):')
    compile(text,name,'exec')
    (PACKAGE/'rollback'/name).write_bytes(data)
    new=text.encode('utf-8')
    (PACKAGE/'deploy'/name).write_bytes(new)
    after[remote]=hashlib.sha256(new).hexdigest()
  manifest={**baseline,'version':'hca-r2-1100ms','changed':list(originals),
            'before_sha256':before,'after_sha256':after,
            'parameters':{**baseline['parameters'],'standby_s':1.1,'standby_frames':55,
                          'prediction_horizon_s':1.3,'prediction_margin_s':.2},
            'unchanged':['PID','entry/abort thresholds','150s search','240s software takeover',
                         'driver/data immediate aborts','cruise','diag1 capture','panda safety'],
            'deployment_status':'local candidate only; not installed'}
  (PACKAGE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
  print(json.dumps({'built':str(PACKAGE),'changed':list(originals),'installed':False}))


if __name__=='__main__':build()
