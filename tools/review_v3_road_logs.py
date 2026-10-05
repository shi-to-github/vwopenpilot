"""Read-only summary of saved V3 JSONL traces; never connects to a vehicle."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
import json
from pathlib import Path


BUTTONS = ('up_short', 'down_short', 'recall', 'cancel', 'set',
           'up_long', 'down_long', 'tip_up', 'tip_down')


def when(row):
  return row.get('t_mono_ns', round(row.get('boot_s', 0) * 1e9)) / 1e9


def runs(rows, predicate, maximum_gap=.25):
  result, current = [], []
  for row in rows:
    if predicate(row):
      if current and when(row) - when(current[-1]) > maximum_gap:
        result.append(current)
        current = []
      current.append(row)
    elif current:
      result.append(current)
      current = []
  if current:
    result.append(current)
  return result


def describe_run(group):
  return {'start_s': round(when(group[0]), 3), 'end_s': round(when(group[-1]), 3),
          'duration_s': round(when(group[-1]) - when(group[0]), 3), 'samples': len(group)}


def review(path):
  by_type = {}
  invalid = 0
  with path.open(encoding='utf-8') as source:
    for line in source:
      try:
        row = json.loads(line)
      except ValueError:
        invalid += 1
        continue
      by_type.setdefault(row.get('type', 'unknown'), []).append(row)
  status = sorted(by_type.get('pq46_status', []), key=when)
  status_times = [when(r) for r in status]
  moving = [r for r in status if r['actual_kph'] >= 50]
  seeking = [r for r in status if r['hca']['elapsed_s'] >= 180]
  windows = runs(status, lambda r: r['window_ok'])
  seeking_windows = runs(status, lambda r: r['window_ok'] and r['hca']['elapsed_s'] >= 180)
  transitions = []
  previous = None
  for r in status:
    state = (r['hca']['phase'], r['cruise']['mode'], r['cruise']['phase'], r['cruise']['reason'])
    if state != previous:
      transitions.append({'t_s': round(when(r), 3), 'hca': r['hca'], 'cruise': r['cruise'],
                          'target': r['motor_target_kph'], 'speed': round(r['actual_kph'], 2),
                          'window_reason': r['window_reason']})
      previous = state
  sends = sorted([r for r in by_type.get('sendcan', []) if r['address'] == 906], key=when)
  gra = sorted([r for r in by_type.get('can', []) if r['address'] == 906], key=when)
  native = [r for r in gra if r['src'] == 0]
  native_times = [when(r) for r in native]
  returned = [r for r in gra if r['src'] >= 128]
  returns_by_data = {}
  for r in returned:
    returns_by_data.setdefault((r['src'], r['data']), []).append(when(r))
  motor = sorted([r for r in by_type.get('can', []) if r['address'] == 648 and r['src'] == 0], key=when)
  motor_times = [when(r) for r in motor]
  bursts = []
  current = []
  for row in sends:
    if current and when(row) - when(current[-1]) > .15:
      bursts.append(current)
      current = []
    current.append(row)
  if current:
    bursts.append(current)
  burst_summaries = []
  for burst in bursts:
    start, end = when(burst[0]), when(burst[-1])
    mi = max(0, bisect_right(motor_times, start) - 1)
    after = motor[bisect_left(motor_times, start):bisect_right(motor_times, end + 2.5)]
    echoes, conflicts, delays = 0, 0, []
    for row in burst:
      t = when(row)
      possible = returns_by_data.get((row['src'] + 128, row['data']), [])
      ei = bisect_left(possible, t)
      if ei < len(possible) and possible[ei] - t < .1:
        echoes += 1
      ni = bisect_right(native_times, t)
      if ni < len(native) and native_times[ni] - t < .035:
        next_row = native[ni]
        if next_row['counter'] == row['counter'] and not any(next_row.get(b) for b in BUTTONS):
          conflicts += 1
          delays.append(round((native_times[ni] - t) * 1000, 2))
    si = max(0, bisect_right(status_times, start) - 1)
    before = motor[mi]['stock_set_kph'] if motor else None
    burst_summaries.append({**describe_run(burst),
      'frames': [{'t_s': round(when(r), 4), 'src': r['src'], 'data': r['data'],
                  'counter': r['counter'], 'buttons': [b for b in BUTTONS if r.get(b)]} for r in burst],
      'returned_frames': echoes, 'following_neutral_same_counter': conflicts,
      'following_neutral_delay_ms': delays, 'target_before': before,
      'target_after_unique': sorted(set(r['stock_set_kph'] for r in after)),
      'runtime_before': status[si] if status else None})
  manual = runs(native, lambda r: any(r.get(b) for b in BUTTONS), maximum_gap=.04)
  hca_frames = sorted([r for r in by_type.get('sendcan', []) if r['address'] == 210], key=when)
  quiet_torque = Counter()
  for row in hca_frames:
    t = when(row)
    si = bisect_right(status_times, t) - 1
    if si < 0 or t - status_times[si] > .25:
      continue
    snapshot = status[si]
    if snapshot['hca']['elapsed_s'] >= 180 and snapshot['window_ok']:
      quiet_torque['total'] += 1
      quiet_torque['transmitted_torque_over_30' if abs(row['torque_cnm']) > 30
                   else 'transmitted_torque_le_30'] += 1
  standby_runs = []
  for group in runs(hca_frames, lambda r: r['hca_status'] == 3, maximum_gap=.04):
    start, end = when(group[0]), when(group[-1])
    nearby = status[bisect_left(status_times, start):bisect_right(status_times, end + .02)]
    if any(r['hca']['phase'] == 'standby' for r in nearby):
      standby_runs.append({**describe_run(group),
                           'disabled_duration_to_next_frame_s': round(end - start + .02, 3)})
  controls = by_type.get('controlsState', [])
  summary = {
    'file': path.name, 'invalid_lines': invalid,
    'types': {k: len(v) for k, v in by_type.items()},
    'status_span': [when(status[0]), when(status[-1])] if status else [],
    'status_samples': len(status), 'moving_samples': len(moving),
    'hca_phase': dict(Counter(r['hca']['phase'] for r in status)),
    'hca_max_elapsed_s': max((r['hca']['elapsed_s'] for r in status), default=0),
    'hca_max_completed': max((r['hca']['completed'] for r in status), default=0),
    'hca_max_aborted': max((r['hca']['aborted'] for r in status), default=0),
    'hca_seeking_samples': len(seeking),
    'quiet_seeking_transmitted_torque': dict(quiet_torque),
    'standby_disabled_runs': standby_runs,
    'window_reasons_moving': dict(Counter(r['window_reason'] for r in moving)),
    'window_reasons_seeking': dict(Counter(r['window_reason'] for r in seeking)),
    'window_runs': sorted([describe_run(g) for g in windows], key=lambda r: -r['duration_s'])[:12],
    'seeking_window_runs': sorted([describe_run(g) for g in seeking_windows], key=lambda r: -r['duration_s'])[:12],
    'cruise_modes': dict(Counter(r['cruise']['mode'] for r in status)),
    'cruise_phases': dict(Counter(r['cruise']['phase'] for r in status)),
    'cruise_reasons': dict(Counter(r['cruise']['reason'] for r in status)),
    'controls_active_samples': sum(r['controls_active'] for r in controls),
    'operator_events': by_type.get('operator', []),
    'panda_states_unique': sorted({json.dumps(r.get('pandas'), sort_keys=True) for r in by_type.get('pandaStates', [])}),
    'gra_sources': dict(Counter(r['src'] for r in gra)),
    'injected_bursts': burst_summaries,
    'manual_bursts': [{**describe_run(g), 'buttons': dict(Counter(b for r in g for b in BUTTONS if r.get(b))),
                       'first_data': g[0]['data'], 'last_data': g[-1]['data']} for g in manual],
    'transitions': transitions,
  }
  return summary


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('folder', type=Path)
  args = parser.parse_args()
  summaries = []
  for path in sorted(args.folder.glob('v3-*.jsonl')):
    if 'install-passive' in path.name:
      continue
    result = review(path)
    summaries.append(result)
    compact = {k: v for k, v in result.items() if k not in ('transitions', 'operator_events', 'manual_bursts', 'injected_bursts')}
    compact['injected_bursts'] = [{k: v for k, v in b.items() if k not in ('frames', 'runtime_before')} for b in result['injected_bursts']]
    print(json.dumps(compact, ensure_ascii=True))
  (args.folder / 'analysis.json').write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
  main()
