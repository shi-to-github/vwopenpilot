"""Evidence-bundle extraction: windows, verdicts, hashes and whitelisted fields."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('extract', ROOT / 'tools/extract_hca_evidence.py')
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)


def eps(t, status):
  return {'type': 'can', 't_mono_ns': int(t * 1e9), 'address': 978,
          'name': 'Lenkhilfe_2', 'eps_hca_status': status}


def hca(t, **fields):
  base = {'version': 'hca-r4-forced', 'phase': 'standby', 'elapsed_s': 0.0,
          'cycle': 1, 'completed': 0, 'forced_completed': 0, 'aborted': 0,
          'forced_aborted': 0, 'natural_resets': 0, 'forced_prompts': 0,
          'notice_cancelled': 0, 'forced_pause': False, 'forced_prompt': False,
          'takeover_required': False, 'last_abort_reason': '', 'start_block_reason': '',
          'prompt_id': '', 'notice_id': '', 'driver': {'steeringTorque': 999}}
  base.update(fields)
  return {'type': 'pq46_status', 't_mono_ns': int(t * 1e9), 'hca': base}


class ExtractTests(unittest.TestCase):
  def run_tool(self, lines, window_s=25.0):
    with tempfile.TemporaryDirectory() as tmp:
      trace = Path(tmp) / 'v3-test.jsonl'
      trace.write_text('\n'.join(json.dumps(r) for r in lines) + '\n', encoding='utf-8')
      digest = hashlib.sha256(trace.read_bytes()).hexdigest()
      out = Path(tmp) / 'evidence'
      import sys
      argv = sys.argv
      sys.argv = ['extract', str(trace), '--out', str(out), '--window-s', str(window_s)]
      try:
        extract.main()
      finally:
        sys.argv = argv
      windows = [json.loads(l) for l in (out / 'hca-windows.jsonl').read_text(encoding='utf-8').splitlines()]
      manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
      return windows, manifest, digest, trace.name

  def test_effective_pause_yields_no_refusal_verdict(self):
    lines = [hca(10, cycle=1)]
    lines += [eps(10 + i * .05, 5) for i in range(20)]
    lines.append(hca(11, forced_completed=1, cycle=2, phase='forced_reset_complete'))
    lines += [eps(11 + i * .05, 5) for i in range(300)]
    windows, manifest, _, _ = self.run_tool(lines)
    self.assertEqual(manifest['pause_windows'], 1)
    self.assertEqual(manifest['windows'][0]['verdict'], 'no_refusal_in_window')
    self.assertEqual(manifest['windows'][0]['counter'], 'forced_completed')
    self.assertEqual(manifest['eps_status_histogram'], {'active': 320})
    self.assertEqual(manifest['refusals_outside_any_pause_s'], [])

  def test_ineffective_pause_is_reported_as_insufficient(self):
    lines = [hca(10)]
    lines.append(hca(11, forced_completed=1, cycle=2))
    lines += [eps(11 + i * .05, 5) for i in range(80)]
    lines += [eps(15 + i * .05, 4) for i in range(40)]
    windows, manifest, _, _ = self.run_tool(lines)
    self.assertEqual(manifest['windows'][0]['verdict'], 'insufficient_standby')
    self.assertTrue(manifest['windows'][0]['refused_at_s'])
    self.assertAlmostEqual(manifest['windows'][0]['refused_at_s'][0], 4.0, delta=.2)
    self.assertEqual(manifest['eps_status_histogram'].get('refused'), 40)

  def test_refusal_outside_a_pause_is_flagged_as_hardware_timeout(self):
    lines = [eps(5, 5), eps(5.5, 5), eps(6, 4), eps(6.5, 2), hca(7, natural_resets=1)]
    _, manifest, _, _ = self.run_tool(lines)
    self.assertEqual(manifest['pause_windows'], 0)
    self.assertEqual(manifest['refusals_outside_any_pause_s'], [6.0, 6.5])

  def test_sources_are_hashed_and_private_fields_are_dropped(self):
    lines = [hca(10, forced_completed=1, cycle=2, driver={'steeringTorque': 12345}),
             eps(10.1, 5)]
    windows, manifest, digest, name = self.run_tool(lines)
    self.assertEqual(manifest['sources'][0]['sha256'], digest)
    self.assertEqual(manifest['sources'][0]['name'], name)
    blob = json.dumps(windows, ensure_ascii=False)
    self.assertNotIn('steeringTorque', blob)
    self.assertNotIn('12345', blob)
    for record in windows:
      self.assertIn(record['kind'], ('counter', 'eps'))


if __name__ == '__main__':
  unittest.main()
