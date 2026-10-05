"""Approximate entry-only shadow replay, never predicts post-pause vehicle motion."""
from bisect import bisect_right
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
def load(version):
  source=ROOT/('candidate/device-a6eed9e-v3-'+version+'/deploy/hca_timer_reset.py')
  spec=importlib.util.spec_from_file_location(version,source)
  mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
  return mod.HcaTimerReset

def replay(folder):
  status=[];commands=[]
  for file in sorted(folder.glob('v3-20*.jsonl')):
    for line in file.open(encoding='utf-8'):
      row=json.loads(line)
      if row['type']=='pq46_status':status.append(row)
      elif row['type']=='carControl':commands.append(row)
  status.sort(key=lambda r:r['t_mono_ns']);commands.sort(key=lambda r:r['t_mono_ns'])
  st=[r['t_mono_ns'] for r in status];ct=[r['t_mono_ns'] for r in commands]
  versions={'r1':load('hca-r1'),'r2':load('hca-r2-entry')}
  epochs=[];epoch=0;previous_age=0;previous_stamp=0
  # Per-epoch first candidate only: after that a counterfactual vehicle path
  # would be required, so no fabricated pause completions are evaluated.
  for row in status:
    age=row['hca']['elapsed_s']
    if age+1<previous_age or row['t_mono_ns']-previous_stamp>1_000_000_000:
      epoch+=1
    row['_epoch']=epoch;previous_age=age;previous_stamp=row['t_mono_ns']
  timers={key:cls() for key,cls in versions.items()}
  found={};previous_epoch=None;last_t=None
  step=20_000_000
  for t in range(max(st[0],ct[0]),min(st[-1],ct[-1])+1,step):
    si=bisect_right(st,t)-1;ci=bisect_right(ct,t)-1
    if si<0 or ci<0:continue
    s,c=status[si],commands[ci];epoch=s['_epoch']
    if previous_epoch!=epoch:
      timers={key:cls() for key,cls in versions.items()};previous_epoch=epoch
    if (t-st[si]>.2e9 or t-ct[ci]>.12e9 or not c['message_valid'] or
        not c['latActive'] or s['hca']['phase'] in ('standby','reset_complete','inactive')):
      for timer in timers.values():timer.update(False,0)
      continue
    raw=round(c['requested']['steer']*300)
    limited=c['applied']['steerOutputCan']
    for version,timer in timers.items():
      if (epoch,version) in found:continue
      timer.elapsed=max(0,round(s['hca']['elapsed_s']*50)-1)
      timer.update(True,limited,raw_torque=raw,window_ok=s['window_ok'],
                   driver_input=s['hca']['driver_input'],continue_ok=s['continue_ok'],
                   window_reason=s['window_reason'],continue_reason=s['continue_reason'])
      if timer.standby:
        found[epoch,version]={'t_s':t/1e9,'observed_age_s':s['hca']['elapsed_s'],
                              'raw':raw,'limited':limited,'center_m':s['geometry'].get('center_m')}
  for epoch in sorted({e for e,v in found}):
    epochs.append({'epoch':epoch,**{v:found.get((epoch,v)) for v in versions}})
  result={'kind':'approximate entry-only shadow comparison',
          'limitations':'20 Hz request and 10 Hz geometry held to a 50 Hz grid; observed path only; no pause outcome or EPS reset prediction',
          'epochs_with_first_candidate':{v:sum((e,v) in found for e in {r['_epoch'] for r in status}) for v in versions},
          'epochs':epochs}
  (folder/'r2-entry-shadow.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
  print(json.dumps(result))

if __name__=='__main__':replay(Path(sys.argv[1]))
