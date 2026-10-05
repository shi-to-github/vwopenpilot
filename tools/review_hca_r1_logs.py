"""Read-only HCA-r1 review, including transmitted standby and EPS feedback."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

from review_v3_road_logs import when, runs


def review(folder):
  data = {}
  sessions = []
  for path in sorted(folder.glob('v3-20*.jsonl')):
    count = Counter()
    first = last = None
    start = None
    for line in path.open(encoding='utf-8'):
      row = json.loads(line)
      kind = row['type']
      count[kind] += 1
      if kind == 'session':
        start = row['started_unix_ns'] / 1e9
      if 't_mono_ns' in row:
        t = when(row)
        first = t if first is None else min(first, t)
        last = t if last is None else max(last, t)
      if kind in ('pq46_status', 'controlsState', 'carState', 'pandaStates', 'operator') or (
          kind == 'sendcan' and row['address'] in (210, 906)) or (
          kind == 'can' and row['address'] == 978 and row['src'] == 0):
        data.setdefault(kind, []).append(row)
    sessions.append({'file': path.name, 'started_unix_s': start, 'first_s': first,
                     'last_s': last, 'duration_s': last - first, 'counts': dict(count)})
  for rows in data.values():
    rows.sort(key=when)
  offset = sessions[0]['started_unix_s'] - sessions[0]['first_s']
  def clock(t):
    return datetime.fromtimestamp(t + offset, timezone(timedelta(hours=8))).isoformat(timespec='seconds')
  status = data['pq46_status']
  sts = [when(r) for r in status]
  controls = data['controlsState']
  cts = [when(r) for r in controls]
  eps = data['can']
  et = [when(r) for r in eps]
  hca = [r for r in data['sendcan'] if r['address'] == 210]
  eps_names = {0: 'disabled', 1: 'initializing', 2: 'fault', 3: 'ready', 4: 'rejected', 5: 'active'}
  def eps_counts(a, b):
    return dict(Counter(eps_names.get(r['eps_hca_status'], str(r['eps_hca_status']))
                        for r in eps[bisect_left(et, a):bisect_right(et, b)]))
  events = []
  previous = status[0]
  for row in status[1:]:
    p, h = previous['hca'], row['hca']
    t = when(row)
    for counter in ('completed', 'aborted', 'natural_resets'):
      if h[counter] > p[counter]:
        events.append({'kind': counter, 'time': clock(t), 't_s': t, 'hca': h,
                       'speed_kph': row['actual_kph'], 'geometry': row.get('geometry'),
                       'center_rate_mps': row.get('center_rate_mps'),
                       'driver': row.get('driver'), 'previous_hca': p,
                       'eps_before': eps_counts(t - 3, t - 2),
                       'eps_near': eps_counts(t - 2, t + .1),
                       'eps_after': eps_counts(t + .1, t + 2)})
    if h['takeover_required'] and not p['takeover_required']:
      events.append({'kind': 'deadline', 'time': clock(t), 't_s': t,
                     'hca': h, 'speed_kph': row['actual_kph'],
                     'eps_before': eps_counts(t - 2, t)})
    previous = row
  off = []
  for group in runs(hca, lambda r: r['hca_status'] == 3, maximum_gap=.04):
    a, b = when(group[0]), when(group[-1])
    snapshots = status[bisect_left(sts, a):bisect_right(sts, b + .12)]
    if not (any(r['hca']['phase'] == 'standby' for r in snapshots) or any(
        e['kind'] in ('aborted', 'completed') and 0 <= e['t_s'] - b <= .15 for e in events)):
      continue
    ci = max(0, bisect_right(cts, a) - 1)
    window = controls[ci:bisect_right(cts, b + 1)]
    off.append({'time': clock(a), 'start_s': a, 'end_s': b, 'frames': len(group),
                'span_plus_one_frame_s': b - a + .02,
                'eps_during': eps_counts(a, b), 'eps_after': eps_counts(b + .02, b + 2),
                'controls_remained_active': all(r['controls_active'] for r in window),
                'start_snapshot': snapshots[0] if snapshots else None,
                'last_snapshot': snapshots[-1] if snapshots else None})
  for e in events:
    if e['kind'] == 'deadline':
      t = e['t_s']
      future_controls = controls[bisect_left(cts,t):bisect_right(cts,t+10)]
      inactive = next((r for r in future_controls if not r['controls_active']), None)
      e['controls_inactive_after_s'] = when(inactive)-t if inactive else None
  panda_changes = []
  prior_pandas = None
  for r in data['pandaStates']:
    blocked = [p.get('safetyTxBlocked') for p in r['pandas']]
    if blocked != prior_pandas:
      panda_changes.append({'time':clock(when(r)), 't_s':when(r), 'blocked':blocked,
                            'pandas':r['pandas']})
      prior_pandas = blocked
  seek = [r for r in status if r['hca']['lat_active'] and
          r['hca']['elapsed_s'] >= r['hca'].get('seek_after_s', 180)]
  seeking_stable = []
  for group in runs(status, lambda r: r['hca']['lat_active'] and
                    r['hca']['elapsed_s'] >= r['hca'].get('seek_after_s', 180)
                    and r['window_ok'], maximum_gap=.25):
    if when(group[-1]) - when(group[0]) >= 2:
      seeking_stable.append({'time': clock(when(group[0])), 'duration_s': when(group[-1])-when(group[0]),
                             'max_raw': max(abs(r['hca']['raw_torque']) for r in group),
                             'blocking': dict(Counter(r['hca']['start_block_reason'] for r in group))})
  buttons = ('up_short', 'down_short', 'recall', 'cancel', 'set', 'up_long', 'down_long', 'tip_up', 'tip_down')
  result = {'sessions': sessions, 'time_basis': 'session wall clock aligned to first CAN/event timestamp; approximate',
            'covered_minutes': sum(s['duration_s'] for s in sessions)/60,
            'version': dict(Counter(r['hca'].get('version') for r in status)),
            'events': events, 'planned_off_runs': off,
            'seeking_blockers': dict(Counter(r['hca']['start_block_reason'] for r in seek)),
            'seeking_stable_windows': seeking_stable,
            'eps_all': eps_counts(et[0], et[-1]),
            'eps_rejected_runs': [{'time': clock(when(g[0])), 'duration_s': when(g[-1])-when(g[0])}
                                  for g in runs(eps, lambda r:r['eps_hca_status']==4, maximum_gap=.12)],
            'cruise_modes': dict(Counter(r['cruise']['mode'] for r in status)),
            'panda_blocked_changes': panda_changes,
            'sent_gra_buttons': dict(Counter(b for r in data['sendcan'] if r['address']==906
                                            for b in buttons if r.get(b))),
            'operator': data.get('operator', []),
            'speed_range': [min(r['actual_kph'] for r in status), max(r['actual_kph'] for r in status)]}
  (folder/'hca-r1-analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps({k:v for k,v in result.items() if k not in ('events','planned_off_runs','operator')}, ensure_ascii=True))
  print('EVENTS')
  for e in events:
    print(json.dumps({k:v for k,v in e.items() if k not in ('geometry','driver','previous_hca')},ensure_ascii=True))
  print('OFF RUNS')
  for r in off:
    print(json.dumps({k:v for k,v in r.items() if k not in ('start_snapshot','last_snapshot')},ensure_ascii=True))
  return result


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('folder', type=Path)
  review(parser.parse_args().folder)
