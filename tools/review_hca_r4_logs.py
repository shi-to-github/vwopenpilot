"""Read-only review of hca-r4-forced traces.

The software counter is not the rack's internal counter, so a completed forced
pause proves nothing by itself. The only verdict is the raw Lenkhilfe_2 (978)
status right after the pause resumes:

  eps_hca_status 5     HCA active
  eps_hca_status 3     HCA ready / idle
  eps_hca_status 2, 4  rack refused the request

A refusal inside the observation window that follows a forced pause means the
forced standby was too short for this rack. A refusal outside any pause is the
original ~360 s hardware timeout still happening.

Usage: python tools/review_hca_r4_logs.py <trace.jsonl> [...] [--json out.json]
       [--window-s 25]
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

REFUSED = (2, 4)
ACTIVE = 5
READY = 3
COUNTERS = ('completed', 'forced_completed', 'aborted', 'forced_aborted',
            'natural_resets', 'forced_prompts', 'notice_cancelled', 'cycle')


def load(paths):
  status, eps = [], []
  for path in paths:
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
      line = line.strip()
      if not line:
        continue
      try:
        record = json.loads(line)
      except ValueError:
        continue
      when = record.get('t_mono_ns')
      if not isinstance(when, (int, float)):
        continue
      when /= 1e9
      if record.get('type') == 'pq46_status' and isinstance(record.get('hca'), dict):
        status.append((when, record))
      elif record.get('eps_hca_status') is not None:
        eps.append((when, record['eps_hca_status']))
  status.sort(key=lambda item: item[0])
  eps.sort(key=lambda item: item[0])
  return status, eps


def eps_label(value):
  return 'active' if value == ACTIVE else 'ready' if value == READY else \
         'REJECTED' if value in REFUSED else 'status%s' % value


def main():
  parser = argparse.ArgumentParser(description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('traces', nargs='+', type=Path)
  parser.add_argument('--json', type=Path)
  parser.add_argument('--window-s', type=float, default=25.0,
                      help='how long after a forced pause the rack may still refuse')
  args = parser.parse_args()

  status, eps = load(args.traces)
  if not status:
    raise SystemExit('No pq46_status records found')

  last = {name: 0 for name in COUNTERS}
  events, pauses, blocks = [], [], Counter()
  eps_counts = Counter(eps_label(value) for _, value in eps)
  for when, record in status:
    hca = record['hca']
    for name in COUNTERS:
      value = hca.get(name)
      if isinstance(value, int) and value > last[name]:
        if name != 'cycle' or last['cycle']:
          events.append({'t_s': when, 'counter': name,
                         'from': last[name], 'to': value,
                         'elapsed_s': hca.get('elapsed_s'),
                         'phase': hca.get('phase'),
                         'last_abort_reason': hca.get('last_abort_reason')})
        last[name] = value
    reason = hca.get('start_block_reason')
    if reason and hca.get('phase') in ('seeking', 'late_seeking', 'forced_prompt'):
      blocks[reason] += 1
    if hca.get('phase') == 'forced_standby':
      pauses.append(when)

  resumes = []
  for event in events:
    if event['counter'] != 'forced_completed':
      continue
    start = event['t_s']
    end = start + args.window_s
    window = [(w, v) for w, v in eps if start <= w <= end]
    refused = [w for w, v in window if v in REFUSED]
    resumes.append({'forced_completed_at_s': round(start, 3),
                    'observed_s': round(window[-1][0] - start, 3) if window else 0.0,
                    'eps_frames': len(window),
                    'eps_statuses': dict(Counter(eps_label(v) for _, v in window)),
                    'refused_at_s': [round(w - start, 3) for w in refused[:5]],
                    'verdict': 'insufficient_1.1s' if refused else 'no_refusal_in_window'})

  outside = []
  for when, value in eps:
    if value not in REFUSED:
      continue
    in_pause = any(abs(when - p) <= 2.0 for p in pauses)
    if not in_pause:
      outside.append(round(when, 3))

  opportunistic = {name: last[name] for name in COUNTERS}
  report = {'traces': [str(p) for p in args.traces],
            'pq46_status_records': len(status),
            'eps_frames': len(eps), 'eps_statuses': dict(eps_counts),
            'counters': opportunistic,
            'forced_pauses': len(pauses) and len(resumes),
            'forced_pause_verdicts': resumes,
            'refusals_outside_a_pause_s': outside[:20],
            'start_block_reasons': dict(blocks.most_common()),
            'counter_events': events}
  print(json.dumps({k: report[k] for k in
                    ('pq46_status_records', 'eps_frames', 'eps_statuses', 'counters',
                     'start_block_reasons')}, ensure_ascii=False, indent=2))
  print('forced pauses completed: %d' % len(resumes))
  for item in resumes:
    print('  +%8.3fs  %-20s %s' % (item['forced_completed_at_s'],
                                   item['verdict'], item['eps_statuses']))
    if item['refused_at_s']:
      print('           refused at +%s s after the pause' % item['refused_at_s'])
  if outside:
    print('refusals outside any pause (original ~360 s timeout): %s' % outside[:10])
  if not resumes:
    print('no completed forced pause in these traces')
  if args.json:
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('wrote %s' % args.json)


if __name__ == '__main__':
  main()
