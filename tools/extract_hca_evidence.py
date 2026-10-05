"""Extract a small, publishable HCA evidence bundle from raw road traces.

Raw v3-*.jsonl traces are far too large to publish, and most of their content is
irrelevant. The decisive evidence is narrow: the raw Lenkhilfe_2 (978) HCA status
and the scheduler counters, around every completed standby pause.

Outputs, into --out:
  hca-windows.jsonl  compact records: eps status frames and hca status inside each
                     pause window, plus every counter change in the whole trace
  manifest.json      source file names, sizes and SHA-256, row counts, per-window
                     verdicts and whole-trace EPS status histogram

The verdict rule is the same one tools/review_hca_r4_logs.py uses: a refusal
(status 2 or 4) shortly after a completed pause means the standby was too short.
This tool only reports; it never concludes "safe".

Usage:
  python tools/extract_hca_evidence.py trace.jsonl [more.jsonl ...] --out evidence
"""
import argparse
import hashlib
import json
from pathlib import Path

VERSION = 1
REFUSED = (2, 4)
COUNTERS = ('completed', 'forced_completed', 'aborted', 'forced_aborted',
            'natural_resets', 'forced_prompts', 'notice_cancelled', 'cycle')
HCA_FIELDS = ('version', 'phase', 'elapsed_s', 'cycle', 'completed', 'forced_completed',
              'aborted', 'forced_aborted', 'natural_resets', 'forced_prompts',
              'notice_cancelled', 'forced_pause', 'forced_prompt', 'takeover_required',
              'last_abort_reason', 'start_block_reason', 'prompt_id', 'notice_id')


def label(value):
  return 'active' if value == 5 else 'ready' if value == 3 else \
         'refused' if value in REFUSED else 'status%s' % value


def stream(path):
  """Yield (t_seconds, record) for the records worth keeping, without loading all."""
  with path.open(encoding='utf-8', errors='replace') as handle:
    for line in handle:
      if '"pq46_status"' not in line and '"eps_hca_status"' not in line:
        continue
      try:
        record = json.loads(line)
      except ValueError:
        continue
      when = record.get('t_mono_ns')
      if not isinstance(when, (int, float)):
        continue
      yield when / 1e9, record


def main():
  parser = argparse.ArgumentParser(description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('traces', nargs='+', type=Path)
  parser.add_argument('--out', type=Path, default=Path('evidence'))
  parser.add_argument('--window-s', type=float, default=25.0,
                      help='observation window after each completed pause')
  args = parser.parse_args()

  args.out.mkdir(parents=True, exist_ok=True)
  eps = []            # (t, status) for the whole trace
  status = []         # (t, hca dict)
  sources = []
  for path in args.traces:
    raw = path.read_bytes()
    sources.append({'name': path.name, 'bytes': len(raw),
                    'sha256': hashlib.sha256(raw).hexdigest()})
    for when, record in stream(path):
      if record.get('eps_hca_status') is not None:
        eps.append((when, record['eps_hca_status']))
      elif isinstance(record.get('hca'), dict):
        status.append((when, record['hca']))
  eps.sort(key=lambda item: item[0])
  status.sort(key=lambda item: item[0])

  # Counter changes anchor the windows.
  counters = {name: 0 for name in COUNTERS}
  changes, pauses = [], []
  for when, hca in status:
    for name in COUNTERS:
      value = hca.get(name)
      if isinstance(value, int) and value > counters[name]:
        changes.append((when, name, counters[name], value, hca))
        if name in ('completed', 'forced_completed'):
          pauses.append((when, name, hca.get('elapsed_s')))
        counters[name] = value

  windows = []
  for when, name, elapsed in pauses:
    end = when + args.window_s
    frames = [(t, s) for t, s in eps if when <= t <= end]
    refused = [t for t, s in frames if s in REFUSED]
    windows.append({'completed_at_s': round(when, 3), 'counter': name,
                    'elapsed_at_completion_s': elapsed,
                    'observed_s': round(frames[-1][0] - when, 3) if frames else 0.0,
                    'eps_frames': len(frames),
                    'refused_at_s': [round(t - when, 3) for t in refused],
                    'verdict': 'insufficient_standby' if refused else 'no_refusal_in_window',
                    'start': when, 'end': end})

  with (args.out / 'hca-windows.jsonl').open('w', encoding='utf-8') as output:
    for when, name, before, after, hca in changes:
      output.write(json.dumps({'t': round(when, 3), 'kind': 'counter', 'counter': name,
                               'from': before, 'to': after,
                               **{k: hca.get(k) for k in HCA_FIELDS}},
                              ensure_ascii=False) + '\n')
    for window in windows:
      for t, s in eps:
        if window['start'] <= t <= window['end']:
          output.write(json.dumps({'t': round(t, 3), 'kind': 'eps',
                                   'status': s, 'label': label(s),
                                   'offset_s': round(t - window['start'], 3),
                                   'window_completed_at_s': round(window['start'], 3)},
                                  ensure_ascii=False) + '\n')

  histogram = {}
  for _, value in eps:
    histogram[label(value)] = histogram.get(label(value), 0) + 1
  outside = [round(t, 3) for t, s in eps if s in REFUSED
             and not any(w['start'] - 2 <= t <= w['end'] for w in windows)]
  manifest = {'tool': 'extract_hca_evidence', 'tool_version': VERSION,
              'window_s': args.window_s,
              'sources': sources,
              'eps_frames_total': len(eps),
              'eps_status_histogram': histogram,
              'counters': counters,
              'pause_windows': len(windows),
              'windows': [{k: v for k, v in w.items() if k not in ('start', 'end')}
                          for w in windows],
              'refusals_outside_any_pause_s': outside[:50],
              'note': ('Raw traces are not published; this bundle carries only the '
                       '978 HCA status frames and scheduler counters around each pause. '
                       'A verdict of no_refusal_in_window means no refusal was observed, '
                       'not that the behaviour is proven safe.')}
  (args.out / 'manifest.json').write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

  print(json.dumps({'windows': len(windows), 'eps_frames': len(eps),
                    'histogram': histogram,
                    'verdicts': [w['verdict'] for w in windows],
                    'out': str(args.out)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
  main()
