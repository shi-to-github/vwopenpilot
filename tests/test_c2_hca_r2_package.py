"""R2 transaction fixtures against the installed r1 plus diag1 baseline."""
import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import unittest

import test_c2_hca_r1_package as old

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'candidate/device-a6eed9e-v3-hca-r2-entry'
spec=importlib.util.spec_from_file_location('r2_manager',ROOT/'tools/manage_c2_hca_r2_entry.py')
manager=importlib.util.module_from_spec(spec);spec.loader.exec_module(manager)

class TransactionTests(unittest.TestCase):
  setUp=old.TransactionTest.setUp
  run_remote=old.TransactionTest.run_remote
  prepare_r1=old.TransactionTest.prepare_r1
  r1_action=old.TransactionTest.r1_action

  def prepare(self):
    self.prepare_r1();self.r1_action('install')
    shutil.copyfile(ROOT/'candidate/device-a6eed9e-v3-hca-r1-diag1/deploy/v3_capture.py',self.data/'v3_capture.py')
    self.r2stage=self.root/'r2-stage';self.r2stage.mkdir()
    self.r2=json.loads((PACKAGE/'manifest.json').read_text(encoding='utf-8'))
    self.r2['base_commit']=self.manifest['base_commit']
    for key in ('before_sha256','after_sha256'):
      self.r2[key]={str(Path(n.replace('/data/openpilot',str(self.base)).replace('/data/pq46/',str(self.data)+'/'))):v
                    for n,v in self.r2[key].items()}
    for sub,prefix in (('deploy','new-'),('rollback','old-')):
      shutil.copyfile(PACKAGE/sub/'hca_timer_reset.py',self.r2stage/(prefix+'hca_timer_reset.py'))

  def action(self,action,bad_smoke=False):
    code=manager.REMOTE
    for oldpath,newpath in (('/data/openpilot',self.base),('/data/pq46_hca_r2_entry_staging',self.r2stage),
                            ('/data/params/d_tmp',self.params),('/data/pq46_hca_staging/update-hold.json',self.hold)):
      code=code.replace('pathlib.Path(%r)'%oldpath,'pathlib.Path(%r)'%str(newpath))
    tree=ast.parse(code)
    for node in ast.walk(tree):
      if isinstance(node,ast.If) and any(isinstance(n,ast.ImportFrom) and n.module=='selfdrive.car.volkswagen.hca_timer_reset' for n in node.body):
        node.body=ast.parse("raise RuntimeError('simulated smoke failure')" if bad_smoke else 'pass').body
    tree.body=[n for n in tree.body if not(isinstance(n,ast.ImportFrom) and n.module=='urllib.request')]
    class Response:
      status=200
      def __enter__(self):return self
      def __exit__(self,*args):pass
      def read(self):return b'{"mode":"base"}'
    from urllib.request import Request
    ns={'CONFIG':self.r2,'ACTION':action,'PARKED_IGNITION':False,
        'Request':Request,'urlopen':lambda *args,**kwargs:Response()}
    output=io.StringIO()
    with contextlib.redirect_stdout(output):exec(compile(ast.fix_missing_locations(tree),'r2_fixture','exec'),ns)
    return [json.loads(line) for line in output.getvalue().splitlines()]

  def test_install_and_rollback_keep_diag_capture_and_other_control_files(self):
    self.prepare();capture=(self.data/'v3_capture.py').read_bytes()
    self.assertEqual(self.action('status')[0]['state'],'HCA_R1_DIAG1_BASELINE')
    self.action('install');self.assertEqual(self.action('status')[0]['state'],'HCA_R2_ENTRY_PRESENT')
    self.action('rollback');self.assertEqual(self.action('status')[0]['state'],'HCA_R1_DIAG1_BASELINE')
    self.assertEqual((self.data/'v3_capture.py').read_bytes(),capture)

  def test_device_smoke_failure_restores_original_timer(self):
    self.prepare()
    with self.assertRaisesRegex(RuntimeError,'smoke failure'):self.action('install',True)
    self.assertEqual(self.action('status')[0]['state'],'HCA_R1_DIAG1_BASELINE')

  def test_unknown_control_change_and_bad_staging_are_rejected(self):
    self.prepare();(self.r2stage/'new-hca_timer_reset.py').write_text('bad')
    with self.assertRaisesRegex(RuntimeError,'Staging hash mismatch'):self.action('install')
    self.assertEqual(self.action('status')[0]['state'],'HCA_R1_DIAG1_BASELINE')
    (self.vw/'carstate.py').write_text('unknown')
    with self.assertRaisesRegex(RuntimeError,'pinned'):self.action('install')

  def test_park_and_update_hold_remain_required(self):
    self.prepare();self.hold.unlink()
    with self.assertRaisesRegex(RuntimeError,'Update hold'):self.action('install')
    self.hold.write_text('{}');(self.params/'IsOffroad').write_text('0')
    with self.assertRaisesRegex(RuntimeError,'Parked ignition'):self.action('install')

if __name__=='__main__':unittest.main()
