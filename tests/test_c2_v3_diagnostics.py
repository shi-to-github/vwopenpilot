"""Test feedback reporting and fail-closed logging without cereal/Android."""
import ast
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DIAG = ROOT / 'candidate/device-a6eed9e-v3/diagnostics'


def load_without_device_imports(path, namespace):
  tree = ast.parse(path.read_text(encoding='utf-8'))
  tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and
              n.module in ('cereal', 'common.realtime'))]
  exec(compile(tree, str(path), 'exec'), namespace)
  return namespace


class DiagnosticsTest(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.directory = Path(self.temp.name)
    self.clock = 10
    self.ns = load_without_device_imports(DIAG / 'v3_server.py',
      {'sec_since_boot': lambda: self.clock, '__name__': 'v3_diagnostics_test'})
    self.ns.update(ROOT=self.directory, LOGS=self.directory / 'logs',
      MODE=self.directory / 'mode.json', EVENTS=self.directory / 'events.jsonl',
      STATUS=self.directory / 'status.json')
    self.session = self.ns['Session']()
    self.addCleanup(self.session.close)

  def test_default_off_and_no_logger_prevents_arming(self):
    self.assertEqual(self.session.status()['mode'], 'base')
    with patch.object(self.session, 'start_recording', side_effect=RuntimeError('logger failure')):
      with self.assertRaisesRegex(RuntimeError, 'logger failure'):
        self.session.set_mode('auto')
    self.assertEqual(self.session.status()['mode'], 'base')

  def test_status_expiry(self):
    self.ns['STATUS'].write_text(json.dumps({'boot_s': 8}), encoding='utf-8')
    self.assertEqual(self.session.status()['runtime'], {})
    self.ns['STATUS'].write_text(json.dumps({'boot_s': 10, 'hca': {'phase': 'seeking'}}), encoding='utf-8')
    self.assertEqual(self.session.status()['runtime']['hca']['phase'], 'seeking')
    self.ns['STATUS'].write_text('[]', encoding='utf-8')
    self.assertEqual(self.session.status()['runtime'], {})

  def test_probe_returns_to_base_only_on_ecu_ack_or_fault(self):
    sm = type('SM', (), {'valid': {'carState': True}, 'alive': {'carState': True},
      'logMonoTime': {'carState': 10e9}, '__getitem__': lambda s, key:
       NS(cruiseState=NS(enabled=True))})()
    with patch.object(self.session, 'start_recording'):
      self.session.set_mode('probe_down')
      for phase, fault, expected in (('wait', '', 'probe_down'), ('fault', 'ecu_ack_timeout', 'base')):
        self.ns['STATUS'].write_text(json.dumps({'boot_s': 10, 'cruise': {
          'mode': 'probe_down', 'phase': phase, 'fault': fault}}), encoding='utf-8')
        self.session.tick(sm, 10)
        self.assertEqual(self.session.mode, expected)
      self.session.set_mode('probe_recall')
      self.ns['STATUS'].write_text(json.dumps({'boot_s': 10, 'cruise': {
        'mode': 'probe_recall', 'phase': 'done', 'direction': 'recall'}}), encoding='utf-8')
      self.session.tick(sm, 10)
      self.assertEqual(self.session.mode, 'base')

  def test_rotation_preserves_earlier_probe_files(self):
    logdir = self.ns['LOGS']
    original = logdir / 'probe-original.jsonl'
    original.write_text('preserve', encoding='utf-8')
    for index in range(21):
      (logdir / ('v3-%02d.jsonl' % index)).write_text('trace', encoding='utf-8')
    self.session.retain()
    self.assertEqual(len(list(logdir.glob('v3-*.jsonl'))), 19)
    self.assertEqual(original.read_text(encoding='utf-8'), 'preserve')

  def test_hca_eps_and_real_button_decoder(self):
    ns = load_without_device_imports(DIAG / 'v3_capture.py', {'__name__': 'capture_test'})
    decode = ns['decode_frame']
    self.assertEqual(decode(210, bytes([0, 0x50, 0x40, 0x80, 0])),
      {'name': 'HCA_1', 'hca_status': 5, 'torque_cnm': -2.0})
    self.assertEqual(decode(978, bytes([0, 0, 4]))['eps_hca_status'], 4)
    self.assertTrue(decode(906, bytes.fromhex('91059400'))['down_short'])
    self.assertTrue(decode(906, bytes([0, 0, 2, 0]))['recall'])
    self.assertEqual(decode(648, bytes([0, 0, 0x40, 4, 62]))['stock_set_kph'], 79.36)


if __name__ == '__main__':
  unittest.main()
