"""Exercise local V3 install/rollback transaction in an isolated fixture."""
import ast
import contextlib
import importlib.util
import io
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'candidate/device-a6eed9e-v3'
V2 = ROOT / 'candidate/device-a6eed9e-v2-probe'
spec = importlib.util.spec_from_file_location('v3_package_manager', ROOT / 'tools/manage_c2_v3_package.py')
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class PackageTest(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.base = self.root / 'openpilot'
    self.vw = self.base / 'selfdrive/car/volkswagen'
    self.vw.mkdir(parents=True)
    self.data = self.root / 'pq46'
    self.data.mkdir()
    self.stage = self.root / 'stage'
    self.stage.mkdir()
    self.params = self.root / 'params'
    self.params.mkdir()
    self.hold = self.root / 'hold.json'
    self.hold.write_text('{}', encoding='utf-8')
    self.ui = self.base / 'selfdrive/ui/ui'
    self.ui.parent.mkdir(parents=True)
    shutil.copyfile(V2 / 'deploy/ui', self.ui)
    self.manifest = json.loads((PACKAGE / 'manifest.json').read_text(encoding='utf-8'))
    for name, value in self.manifest['preconditions_sha256'].items():
      if value is not None:
        shutil.copyfile(PACKAGE / 'rollback' / name, self.vw / name)
    for name in self.manifest['preserved_sha256']:
      shutil.copyfile(V2 / 'deploy' / name, self.vw / name)
    shutil.copyfile(PACKAGE / 'rollback/boot_overlay.py', self.data / 'boot_overlay.py')
    for source, name in manager.sources(self.manifest):
      shutil.copyfile(source, self.stage / name)
    for name, value in (('IsOffroad', '1'), ('DisableUpdates', '1'), ('UpdaterState', 'idle')):
      (self.params / name).write_text(value, encoding='utf-8')
    subprocess.run(['git', '-C', str(self.base), 'init', '-q', '-b', 'beta2_sharan2'], check=True)
    subprocess.run(['git', '-C', str(self.base), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(self.base), '-c', 'user.name=Test', '-c',
                    'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    self.manifest['base_commit'] = subprocess.check_output(
      ['git', '-C', str(self.base), 'rev-parse', 'HEAD'], text=True).strip()
    self.app_calls = []
    self.fail_new_apk = False

  def run_remote(self, action):
    code = manager.REMOTE
    for old, path in (('/data/openpilot', self.base), ('/data/pq46_v3_staging', self.stage),
                      ('/data/pq46', self.data), ('/data/params/d_tmp', self.params),
                      ('/data/pq46_hca_staging/update-hold.json', self.hold)):
      code = code.replace('pathlib.Path(%r)' % old, 'pathlib.Path(%r)' % str(path))
    tree = ast.parse(code)
    for node in tree.body:
      if isinstance(node, ast.FunctionDef) and node.name == 'app_install':
        node.body = ast.parse('__app_install(path)').body
      if isinstance(node, ast.FunctionDef) and node.name == 'stop_backends':
        node.body = ast.parse('pass').body
    def app_install(path):
      self.app_calls.append(path.name)
      if self.fail_new_apk and path.name == 'new-overlay.apk':
        raise RuntimeError('simulated Android install failure')
    ns = {'CONFIG': self.manifest, 'ACTION': action, 'PARKED_IGNITION': False,
          '__app_install': app_install}
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
      exec(compile(ast.fix_missing_locations(tree), 'v3_remote_fixture', 'exec'), ns)
    return json.loads(output.getvalue())

  def test_install_and_full_v2_rollback_preserve_logs(self):
    logs = self.data / 'logs'
    logs.mkdir()
    (logs / 'probe-original.jsonl').write_text('original', encoding='utf-8')
    self.assertEqual(self.run_remote('status')['package_state'], 'READY_FROM_V2')
    self.assertEqual(self.run_remote('install')['action'], 'installed_v3_default_base')
    self.assertEqual(self.run_remote('status')['package_state'], 'V3_PRESENT')
    self.assertTrue((self.stage / 'snapshot-carcontroller.py').exists())
    self.assertEqual(self.run_remote('rollback')['action'], 'rolled_back_to_v2')
    self.assertEqual(self.run_remote('status')['package_state'], 'READY_FROM_V2')
    self.assertEqual((logs / 'probe-original.jsonl').read_text(encoding='utf-8'), 'original')
    self.assertEqual(self.app_calls, ['new-overlay.apk', 'old-overlay.apk'])
    self.assertEqual((self.vw / 'hca_timer_reset.py').read_bytes(),
                     (V2 / 'deploy/hca_timer_reset.py').read_bytes())

  def test_android_failure_restores_all_python_and_startup(self):
    self.fail_new_apk = True
    with self.assertRaisesRegex(RuntimeError, 'simulated Android'):
      self.run_remote('install')
    self.assertEqual(self.run_remote('status')['package_state'], 'READY_FROM_V2')
    self.assertEqual(self.app_calls, ['new-overlay.apk', 'old-overlay.apk'])

  def test_staged_corruption_is_rejected_before_any_changes(self):
    (self.stage / 'new-carcontroller.py').write_text('corrupt', encoding='utf-8')
    with self.assertRaisesRegex(RuntimeError, 'Staged V3 hash'):
      self.run_remote('install')
    self.assertEqual(self.run_remote('status')['package_state'], 'READY_FROM_V2')
    self.assertEqual(self.app_calls, [])

  def test_park_and_update_hold_are_required(self):
    self.hold.unlink()
    with self.assertRaisesRegex(RuntimeError, 'Update hold'):
      self.run_remote('install')
    self.hold.write_text('{}', encoding='utf-8')
    (self.params / 'IsOffroad').write_text('0', encoding='utf-8')
    with self.assertRaisesRegex(RuntimeError, 'offroad'):
      self.run_remote('install')

  def test_unrelated_file_change_is_not_overwritten(self):
    (self.vw / 'interface.py').write_text('custom', encoding='utf-8')
    with self.assertRaisesRegex(RuntimeError, 'differ'):
      self.run_remote('install')
    self.assertEqual((self.vw / 'interface.py').read_text(encoding='utf-8'), 'custom')


class AndroidInboxTest(unittest.TestCase):
  def test_package_service_reads_a_verified_inbox_copy_not_private_staging(self):
    tree = ast.parse(manager.REMOTE)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and
             n.name in ('atomic', 'digest', 'app_install')]
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      inbox = root / 'inbox.apk'
      private = root / 'private.apk'
      private.write_bytes(b'signed apk fixture')
      namespace = {'os': os, 'tempfile': tempfile, 'hashlib': hashlib,
                   'subprocess': subprocess,
                   'pathlib': NS(Path=lambda p: inbox if str(p) == '/data/local/tmp/pq46-v3-install.apk' else Path(p))}
      exec(compile(ast.Module(body=nodes, type_ignores=[]), 'android_inbox_test', 'exec'), namespace)
      calls = []
      def run(args, **kwargs):
        calls.append(args)
        if args[0] == '/system/bin/pm':
          self.assertEqual(args[-1], str(inbox))
          self.assertEqual(inbox.read_bytes(), private.read_bytes())
        return NS(returncode=0, stdout='Success', stderr='')
      with patch.object(subprocess, 'run', side_effect=run):
        namespace['app_install'](private)
      self.assertEqual(len(calls), 2)
      self.assertFalse(inbox.exists())
      self.assertTrue(private.exists())
      with patch.object(subprocess, 'run', return_value=NS(returncode=1, stdout='', stderr='specific install failure')):
        with self.assertRaisesRegex(RuntimeError, 'specific install failure'):
          namespace['app_install'](private)
      self.assertFalse(inbox.exists())


if __name__ == '__main__':
  unittest.main()
