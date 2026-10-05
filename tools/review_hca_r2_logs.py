"""Read-only r2 attribution, using its actual 150-second search threshold."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
import contextlib
import io
import json
from pathlib import Path
from review_hca_diag1_logs import analyze
from review_v3_road_logs import when


def review(folder):
  with contextlib.redirect_stdout(io.StringIO()):
    diag = analyze(folder)
  baseline = json.loads((folder/'hca-r1-analysis.json').read_text(encoding='utf-8'))
  statuses, commands = [], []
  for path in sorted(folder.glob('v3-20*.jsonl')):
    for line in path.open(encoding='utf-8'):
      row = json.loads(line)
      if row['type'] == 'pq46_status': statuses.append(row)
      elif row['type'] == 'carControl': commands.append(row)
  statuses.sort(key=when)
  commands.sort(key=when)
  seeking = [r for r in statuses if r['hca']['lat_active'] and
             r['hca']['seek_after_s'] <= r['hca']['elapsed_s'] < 240 and
             r['hca']['phase'] != 'standby']
  blocker = Counter(r['hca']['start_block_reason'] for r in seeking)
  times = [when(r) for r in statuses]
  command_times = [when(r) for r in commands]
  def pct(n): return round(100*n/len(seeking), 2) if seeking else None
  pauses = []
  for p in diag['pauses']:
    a,b=p['start_s'],p['end_s']
    event = next((e for e in baseline['events'] if e['kind']=='aborted' and
                  0 <= e['t_s']-b <= .15), None)
    near = statuses[bisect_left(times,a):bisect_right(times,b+.12)]
    cmds = commands[bisect_left(command_times,b-.08):bisect_right(command_times,b+.08)]
    pauses.append({'seconds_from_log_start':round(a-baseline['sessions'][0]['first_s'],3),
                   'frames':p['frames'],'duration_s':p['span_plus_one_frame_s'],
                   'abort':event['hca'] if event else None,
                   'geometry_near_abort':near[-1].get('geometry') if near else None,
                   'center_range_m':p['center_range_m'],
                   'max_future_accel':p['model_max_future_lateral_accel_ms2'],
                   'command_near_abort':[{'t_s':when(c),'request':c['requested']['steer']*300,
                                          'applied':c['applied']['steerOutputCan']} for c in cmds],
                   'first_pid':p['first_pid'],'last_pid':p['last_pid'],'peak_pid':p['peak_pid']})
  result={'summary':diag['summary'],'runtime_versions':baseline['version'],
          'search_samples':len(seeking),'search_first_blockers':dict(blocker),
          'first_blocker_percent':{k:pct(v) for k,v in blocker.items()},
          'geometry_future_above_03_percent':pct(sum(r.get('geometry',{}).get('future_lateral_accel_ms2',0)>.3 for r in seeking)),
          'pauses':pauses,'deadline_alerts':diag['deadline_alerts'],
          'gra_buttons_sent':baseline['sent_gra_buttons'],'operator':baseline['operator'],
          'panda_blocked_changes':baseline['panda_blocked_changes'],
          'limitations':'Observed geometry and PID around an abort do not predict the unassisted trajectory if that abort were removed. Device wall clock reset to 2022; durations use monotonic timestamps.'}
  (folder/'r2-analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps({k:v for k,v in result.items() if k not in ('pauses','operator','panda_blocked_changes')},ensure_ascii=True))
  for pause in pauses:print(json.dumps(pause,ensure_ascii=True))
  return result


if __name__=='__main__':
  p=argparse.ArgumentParser(description=__doc__)
  p.add_argument('folder',type=Path)
  review(p.parse_args().folder)
