"""Local transaction fixtures for the pinned three-file HCA-r1 upgrade."""
import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import unittest

import test_c2_v3_package as v3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
PACKAGE = ROOT / 'candidate/device-a6eed9e-v3-hca-r1'
spec = importlib.util.spec_from_file_location('hca_r1_manager', ROOT / 'tools/manage_c2_hca_r1.py')
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class TransactionTest(v3.PackageTest):
  # The inherited V3 tests keep verifying their original baseline transaction.
  def prepare_r1(self):
    self.run_remote('install')
    self.r1stage = self.root / 'hca-r1-stage'
    self.r1stage.mkdir()
    self.r1 = json.loads((PACKAGE / 'manifest.json').read_text(encoding='utf-8'))
    self.r1['base_commit'] = self.manifest['base_commit']
    for key in ('before_sha256', 'after_sha256'):
      mapped = {}
      for name, value in self.r1[key].items():
        name = name.replace('/data/openpilot', str(self.base)).replace('/data/pq46/', str(self.data) + '/')
        mapped[str(Path(name))] = value
      self.r1[key] = mapped
    for name in self.r1['changed']:
      for folder, prefix in (('deploy', 'new-'), ('rollback', 'old-')):
        shutil.copyfile(PACKAGE / folder / name, self.r1stage / (prefix + name))

  def r1_action(self, action, bad_smoke=False):
    code = manager.REMOTE
    for old, path in (('/data/openpilot', self.base), ('/data/pq46_hca_r1_staging', self.r1stage),
                      ('/data/params/d_tmp', self.params), ('/data/pq46_hca_staging/update-hold.json', self.hold)):
      code = code.replace('pathlib.Path(%r)' % old, 'pathlib.Path(%r)' % str(path))
    tree = ast.parse(code)
    # Keep real atomic copies/hash guards, replace only Android/C2 imports.
    for node in ast.walk(tree):
      if (isinstance(node, ast.If) and any(isinstance(n, ast.ImportFrom) and
          n.module == 'selfdrive.car.volkswagen.hca_timer_reset' for n in node.body)):
        node.body = ast.parse("raise RuntimeError('simulated device smoke failure')" if bad_smoke else 'pass').body
    class Response:
      status = 200
      def __enter__(self): return self
      def __exit__(self, *args): pass
      def read(self): return b'{"mode":"base"}'
    ns = {'CONFIG': self.r1, 'ACTION': action, 'PARKED_IGNITION': False}
    # Replace the imported network call, never make an external connection.
    tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and n.module == 'urllib.request')]
    from urllib.request import Request
    ns.update(Request=Request, urlopen=lambda *a, **k: Response())
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
      exec(compile(ast.fix_missing_locations(tree), 'hca_r1_transaction_fixture', 'exec'), ns)
    return [json.loads(line) for line in output.getvalue().splitlines()]

  def test_r1_install_and_rollback_restore_original_v3_and_preserve_logs(self):
    self.prepare_r1()
    logs = self.data / 'logs'
    logs.mkdir()
    (logs / 'road-original.jsonl').write_text('keep', encoding='utf-8')
    self.assertEqual(self.r1_action('status')[0]['state'], 'V3_BASELINE')
    self.assertEqual(self.r1_action('install')[-1]['result'], 'install')
    self.assertEqual(self.r1_action('status')[0]['state'], 'HCA_R1_PRESENT')
    self.assertEqual(self.r1_action('rollback')[-1]['result'], 'rollback')
    self.assertEqual(self.r1_action('status')[0]['state'], 'V3_BASELINE')
    self.assertEqual((logs / 'road-original.jsonl').read_text(encoding='utf-8'), 'keep')
    self.assertEqual(self.app_calls, ['new-overlay.apk'])

  def test_r1_corrupt_staging_and_unrelated_changes_are_rejected(self):
    self.prepare_r1()
    (self.r1stage / 'new-hca_timer_reset.py').write_text('bad', encoding='utf-8')
    with self.assertRaisesRegex(RuntimeError, 'Staging hash mismatch'):
      self.r1_action('install')
    self.assertEqual(self.r1_action('status')[0]['state'], 'V3_BASELINE')
    (self.vw / 'pq46_cruise.py').write_text('unrelated', encoding='utf-8')
    with self.assertRaisesRegex(RuntimeError, 'pinned V3'):
      self.r1_action('install')
    self.assertEqual((self.vw / 'pq46_cruise.py').read_text(encoding='utf-8'), 'unrelated')

  def test_r1_smoke_failure_rolls_all_three_files_back(self):
    self.prepare_r1()
    with self.assertRaisesRegex(RuntimeError, 'smoke failure'):
      self.r1_action('install', bad_smoke=True)
    self.assertEqual(self.r1_action('status')[0]['state'], 'V3_BASELINE')

  def test_r1_update_hold_and_park_are_required(self):
    self.prepare_r1()
    self.hold.unlink()
    with self.assertRaisesRegex(RuntimeError, 'Update hold'):
      self.r1_action('install')
    self.hold.write_text('{}', encoding='utf-8')
    (self.params / 'IsOffroad').write_text('0', encoding='utf-8')
    with self.assertRaisesRegex(RuntimeError, 'Parked ignition'):
      self.r1_action('install')


if __name__ == '__main__':
  unittest.main()
