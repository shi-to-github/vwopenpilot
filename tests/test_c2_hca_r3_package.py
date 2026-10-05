"""Python/APK transaction and rollback fixtures without contacting C2."""
import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import unittest
import test_c2_hca_r2_package as old

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'candidate/device-a6eed9e-v3-hca-r3-staged'
s=importlib.util.spec_from_file_location('r3_manager',ROOT/'tools/manage_c2_hca_r3_staged.py')
manager=importlib.util.module_from_spec(s);s.loader.exec_module(manager)


class PackageTests(unittest.TestCase):
  setUp=old.TransactionTests.setUp
  run_remote=old.TransactionTests.run_remote
  prepare_r1=old.TransactionTests.prepare_r1
  r1_action=old.TransactionTests.r1_action
  prepare=old.TransactionTests.prepare
  action=old.TransactionTests.action
  def setup_r3(self):
    self.prepare();self.action('install')
    self.r3=json.loads((PACKAGE/'manifest.json').read_text())
    self.r3['base_commit']=self.manifest['base_commit']
    def mapped(n):return str(Path(n.replace('/data/openpilot',str(self.base)).replace('/data/pq46/',str(self.data)+'/')))
    for key in ('before_sha256','after_sha256'):
      self.r3[key]={mapped(n):v for n,v in self.r3[key].items()}
    self.r3['changed_targets']={n:mapped(p) for n,p in self.r3['changed_targets'].items()}
    self.r3stage=self.root/'r3-stage';self.r3stage.mkdir()
    for sub,prefix in (('deploy','new-'),('rollback','old-')):
      for name in self.r3['changed']+['overlay.apk']:
        shutil.copyfile(PACKAGE/sub/name,self.r3stage/(prefix+name))
    self.fake_apk=self.r3['apk_sha256']['before']
  def r3_action(self,action,bad_apk=False,bad_smoke=False):
    code=manager.REMOTE
    for oldpath,newpath in (('/data/openpilot',self.base),('/data/pq46',self.data),
                            ('/data/pq46_hca_r3_staged_staging',self.r3stage),('/data/params/d_tmp',self.params),
                            ('/data/pq46_hca_staging/update-hold.json',self.hold)):
      code=code.replace('pathlib.Path(%r)'%oldpath,'pathlib.Path(%r)'%str(newpath))
    tree=ast.parse(code)
    for node in ast.walk(tree):
      if isinstance(node,ast.FunctionDef) and node.name=='current_apk_hash':node.body=ast.parse("return FAKE_APK").body
      if isinstance(node,ast.FunctionDef) and node.name=='app_install':
        node.body=ast.parse("global FAKE_APK\nif BAD_APK and path.name.startswith('new-'): raise RuntimeError('apk install failed')\nFAKE_APK=digest(path)").body
      if isinstance(node,ast.If) and any(isinstance(n,ast.ImportFrom) and n.module=='selfdrive.car.volkswagen.hca_timer_reset' for n in node.body):
        node.body=ast.parse("raise RuntimeError('smoke failed')" if bad_smoke else 'pass').body
    tree.body=[n for n in tree.body if not(isinstance(n,ast.ImportFrom) and n.module=='urllib.request')]
    class Response:
      status=200
      def __enter__(self):return self
      def __exit__(self,*args):pass
      def read(self):return b'{"mode":"base"}'
    from urllib.request import Request
    ns={'CONFIG':self.r3,'ACTION':action,'PARKED_IGNITION':False,'Request':Request,
        'urlopen':lambda *a,**kw:Response(),'FAKE_APK':self.fake_apk,'BAD_APK':bad_apk}
    output=io.StringIO()
    try:
      with contextlib.redirect_stdout(output):exec(compile(ast.fix_missing_locations(tree),'r3_transaction','exec'),ns)
    finally:self.fake_apk=ns['FAKE_APK']
    return [json.loads(line) for line in output.getvalue().splitlines()]
  def test_r3_install_and_full_python_apk_rollback(self):
    self.setup_r3();capture=(self.data/'v3_capture.py').read_bytes()
    self.assertEqual(self.r3_action('status')[0]['state'],'HCA_R2_ENTRY_BASELINE')
    self.r3_action('install');self.assertEqual(self.r3_action('status')[0]['state'],'HCA_R3_STAGED_PRESENT')
    self.r3_action('rollback');self.assertEqual(self.r3_action('status')[0]['state'],'HCA_R2_ENTRY_BASELINE')
    self.assertEqual(capture,(self.data/'v3_capture.py').read_bytes())
  def test_r3_apk_failure_recovers_previous_python_and_apk(self):
    self.setup_r3()
    with self.assertRaisesRegex(RuntimeError,'apk install failed'):self.r3_action('install',bad_apk=True)
    self.assertEqual(self.r3_action('status')[0]['state'],'HCA_R2_ENTRY_BASELINE')
  def test_r3_smoke_failure_recovers_previous_python_and_apk(self):
    self.setup_r3()
    with self.assertRaisesRegex(RuntimeError,'smoke failed'):self.r3_action('install',bad_smoke=True)
    self.assertEqual(self.r3_action('status')[0]['state'],'HCA_R2_ENTRY_BASELINE')
  def test_r3_unknown_apk_and_staging_reject_before_replacement(self):
    self.setup_r3();self.fake_apk='unknown'
    with self.assertRaisesRegex(RuntimeError,'pinned'):self.r3_action('install')
    self.fake_apk=self.r3['apk_sha256']['before'];(self.r3stage/'new-overlay.apk').write_bytes(b'bad')
    with self.assertRaisesRegex(RuntimeError,'APK hash'):self.r3_action('install')
    self.assertEqual(self.r3_action('status')[0]['state'],'HCA_R2_ENTRY_BASELINE')


if __name__=='__main__':unittest.main()
