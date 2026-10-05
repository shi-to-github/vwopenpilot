"""Read-only PID attribution around HCA-r1 planned standby attempts."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
import contextlib
import io
import json
from pathlib import Path

from review_hca_r1_logs import review
from review_v3_road_logs import when


def analyze(folder):
  with contextlib.redirect_stdout(io.StringIO()):
    baseline = review(folder)
  controls, commands, statuses, headers, all_alerts = [], [], [], [], Counter()
  invalid_lines = 0
  for path in sorted(folder.glob('v3-20*.jsonl')):
    for line in path.open(encoding='utf-8'):
      try:
        row = json.loads(line)
      except ValueError:
        invalid_lines += 1
        continue
      if row['type'] == 'controlsState':
        controls.append(row)
        all_alerts[row.get('alertType','')] += 1
      elif row['type'] == 'carControl': commands.append(row)
      elif row['type'] == 'pq46_status': statuses.append(row)
      elif row['type'] == 'session': headers.append({'file':path.name,**row})
  controls.sort(key=when)
  commands.sort(key=when)
  statuses.sort(key=when)
  times = [when(r) for r in controls]
  command_times = [when(r) for r in commands]
  status_times = [when(r) for r in statuses]
  def pid_record(row):
    state = row.get('lateral', {}).get('state', {})
    result = {'t_s':when(row), 'valid':row.get('message_valid'),
              'active':state.get('active'), 'alert':row.get('alertType'),
              'control_state':row.get('control_state')}
    result.update({key:state.get(key) for key in ('steeringAngleDeg','steeringAngleDesiredDeg','angleError')})
    result.update({key+'_scaled':round(state[key]*300,4) for key in ('p','i','f','output') if key in state})
    return result
  analyses = []
  for off in baseline['planned_off_runs']:
    a,b = off['start_s'],off['end_s']
    rows = controls[bisect_left(times,a-.1):bisect_right(times,b+.12)]
    pid_rows = [r for r in rows if r.get('lateral',{}).get('type')=='pidState']
    active = [r for r in pid_rows if r['lateral']['state']['active']]
    peak = max(active,key=lambda r:abs(r['lateral']['state']['output'])) if active else None
    states = statuses[bisect_left(status_times,a):bisect_right(status_times,b+.12)]
    geom = [r['geometry'] for r in states if r.get('geometry',{}).get('valid')]
    cs = commands[bisect_left(command_times,a):bisect_right(command_times,b)]
    event = next((e for e in baseline['events'] if e['kind'] in ('aborted','completed')
                  and 0 <= e['t_s']-b <= .15), None)
    result = {key:off[key] for key in ('time','start_s','end_s','frames','span_plus_one_frame_s',
                                     'controls_remained_active','eps_during','eps_after')}
    result['event'] = {'kind':event['kind'],'reason':event['hca']['last_abort_reason']
                      if event['kind']=='aborted' else ''} if event else None
    result['first_pid'] = pid_record(active[0]) if active else None
    result['last_pid'] = pid_record(active[-1]) if active else None
    result['peak_pid'] = pid_record(peak) if peak else None
    result['series'] = [pid_record(r) for r in active]
    result['center_range_m'] = [min(g['center_m'] for g in geom),max(g['center_m'] for g in geom)] if geom else None
    result['model_max_future_lateral_accel_ms2'] = max((g['future_lateral_accel_ms2'] for g in geom),default=None)
    result['commands_during'] = [{'t_s':when(r),'requested':r['requested']['steer']*300,
                                  'applied':r['applied']['steerOutputCan'],
                                  'latActive':r['latActive']} for r in cs]
    analyses.append(result)
  deadline_alerts = []
  for event in baseline['events']:
    if event['kind'] != 'deadline':continue
    t=event['t_s']
    rows=controls[bisect_left(times,t-1):bisect_right(times,t+6)]
    deadline_alerts.append({'time':event['time'],'t_s':t,'eps_before':event['eps_before'],
                             'controls_inactive_after_s':event['controls_inactive_after_s'],
                             'alerts':dict(Counter(r.get('alertType','') for r in rows)),
                             'control_states':dict(Counter(r.get('control_state','') for r in rows))})
  summary = {'covered_minutes':baseline['covered_minutes'],
             'events':dict(Counter(e['kind'] for e in baseline['events'])),
             'abort_reasons':dict(Counter(e['hca']['last_abort_reason'] for e in baseline['events'] if e['kind']=='aborted')),
             'seeking_blockers':baseline['seeking_blockers'], 'cruise_modes':baseline['cruise_modes'],
             'eps_all':baseline['eps_all'],'eps_rejected_runs':baseline['eps_rejected_runs'],
             'speed_range':baseline['speed_range'],'invalid_lines':invalid_lines,
             'headers':headers,'controls_samples':len(controls),'command_samples':len(commands),
             'all_alerts':dict(all_alerts)}
  result={'summary':summary,'pauses':analyses,'deadline_alerts':deadline_alerts}
  (folder/'diag1-analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps(summary,ensure_ascii=True))
  for pause in analyses:
    print(json.dumps({k:v for k,v in pause.items() if k not in ('series','commands_during')},ensure_ascii=True))
  for deadline in deadline_alerts:print(json.dumps(deadline,ensure_ascii=True))
  return result


if __name__=='__main__':
  parser=argparse.ArgumentParser(description=__doc__)
  parser.add_argument('folder',type=Path)
  analyze(parser.parse_args().folder)
