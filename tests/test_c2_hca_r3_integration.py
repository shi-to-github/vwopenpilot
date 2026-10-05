"""Controller timing, UI acknowledgement, and passive telemetry integration."""
import ast
from collections import deque
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from test_c2_hca_r3_staged import hca,runtime,DEPLOY
from test_c2_v3_diagnostics import load_without_device_imports


class ControllerTests(unittest.TestCase):
  def fixture(self):
    import test_c2_hca_r1 as old
    c,cc,cs=old.IntegrationTest().fixture()
    ns=dict(c.update.__globals__);ns['HcaTimerReset']=hca.HcaTimerReset
    cls=next(n for n in ast.parse((DEPLOY/'carcontroller.py').read_text()).body if isinstance(n,ast.ClassDef))
    exec(compile(ast.Module(body=[cls],type_ignores=[]),'r3_controller','exec'),ns)
    c=ns['CarController'](c.CP.carFingerprint,c.CP,None)
    r=c.pq_runtime
    r.continue_ok=r.delayed_ok=r.notice_ready=True;r.notice_ack=False
    r.window_reason=r.continue_reason=r.delayed_reason='quiet_prediction'
    r.update=lambda speed,remaining,delay,notice_id:r.now
    return c,cc,cs
  def test_driver_abort_restores_existing_rate_limit_and_no_cruise_injection(self):
    c,cc,cs=self.fixture();c.pq_hca_timer_reset=hca.HcaTimerReset(quiet_s=.02)
    c.pq_hca_timer_reset.elapsed=9000
    _,sent=c.update(cc,cs,0);self.assertEqual(sent[0][2]['HCA_Status'],3)
    cs.out.steeringPressed=True;cc.actuators.steer=.5;c.frame=2
    _,sent=c.update(cc,cs,0)
    self.assertEqual(sent[0][2]['LM_Offset'],6)
    self.assertEqual(c.pq_hca_timer_reset.last_abort_reason,'driver_steering')
    self.assertFalse(any(m[0]=='GRA_Neu' for m in sent))
  def test_runtime_receives_reservation_delay_and_remaining_standby(self):
    c,cc,cs=self.fixture();args=[]
    c.pq_runtime.update=lambda *a:args.append(a) or c.pq_runtime.now
    c.update(cc,cs,0);self.assertEqual(args[-1][1:3],(1.1,3))
    c.pq_hca_timer_reset.notice_id='test';c.pq_hca_timer_reset.notice_ticks=50
    c.frame=2;c.update(cc,cs,0)
    self.assertEqual(args[-1][2],2);self.assertEqual(args[-1][3],'test')


class NoticeTests(unittest.TestCase):
  def setUp(self):
    self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    self.root=Path(self.temp.name);self.clock=100
    self.ns=load_without_device_imports(DEPLOY/'v3_server.py',{'sec_since_boot':lambda:self.clock,'__name__':'test_r3_server'})
    self.ns.update(ROOT=self.root,LOGS=self.root/'logs',MODE=self.root/'mode.json',EVENTS=self.root/'events.jsonl',
                   STATUS=self.root/'status.json',UI_STATE=self.root/'ui.json')
    self.session=self.ns['Session']();self.addCleanup(self.session.close)
  def current_notice(self,id='n1'):
    self.ns['STATUS'].write_text(json.dumps({'boot_s':self.clock,'hca':{'version':'hca-r3-staged',
       'phase':'awaiting_notice','notice_id':id}}))
  def test_wrong_or_stale_notice_is_not_acknowledged(self):
    self.current_notice()
    with self.assertRaisesRegex(ValueError,'current'):self.session.ui_heartbeat({'notice_id':'wrong','audio_ok':True})
    self.clock=102
    with self.assertRaisesRegex(ValueError,'current'):self.session.ui_heartbeat({'notice_id':'n1','audio_ok':True})
    self.assertFalse(self.ns['UI_STATE'].exists())
  def test_successful_audio_ack_is_retained_without_restarting_countdown(self):
    self.current_notice();self.session.ui_heartbeat({'audio_ready':True,'notice_id':'n1','audio_ok':True})
    first=json.loads(self.ns['UI_STATE'].read_text());self.assertTrue(first['audio_ok'])
    self.clock=100.5;self.current_notice()
    self.session.ui_heartbeat({'audio_ready':True,'notice_id':'n1','audio_ok':True})
    self.assertEqual(json.loads(self.ns['UI_STATE'].read_text())['ack_boot_s'],100)
    self.assertEqual(len(self.ns['EVENTS'].read_text().splitlines()),1)
  def test_audio_failure_is_logged_but_not_marked_success(self):
    self.current_notice();self.session.ui_heartbeat({'notice_id':'n1','audio_ok':False,'audio_ready':False})
    self.assertFalse(json.loads(self.ns['UI_STATE'].read_text())['audio_ok'])
  def test_heartbeat_cannot_arm_cruise_or_change_mode(self):
    self.session.ui_heartbeat({'audio_ready':True,'mode':'auto'})
    self.assertEqual(self.session.mode,'base');self.assertIsNone(self.session.recorder)


class RuntimeTests(unittest.TestCase):
  def test_actual_standby_horizon_and_future_reservation_are_distinct(self):
    from test_c2_hca_r3_staged import GeometryTests
    r=runtime.Runtime.__new__(runtime.Runtime)
    r.history=deque(maxlen=12);r.last_model_ns=0;r.center_rate=None
    m=GeometryTests().model();m.orientationRate.z[0:4]=[.02]*4
    for i in range(6):r.update_geometry(m,int((100+i*.05)*1e9),100+i*.05,30,1.1,3)
    self.assertFalse(r.window_ok);self.assertTrue(r.delayed_ok)
    self.assertAlmostEqual(r.geometry['prediction_end_s'],1.3)
    self.assertAlmostEqual(r.delayed_geometry['prediction_start_s'],3)
    self.assertAlmostEqual(r.delayed_geometry['prediction_end_s'],4.3)
    m.orientationRate.z=[0]*11
    r.update_geometry(m,int(100.3e9),100.3,30,.2,.5)
    self.assertAlmostEqual(r.geometry['prediction_end_s'],.4)


if __name__=='__main__':unittest.main()
