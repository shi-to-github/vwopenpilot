"""Local stage timing, delivered notices, cancellation and 55-frame reset tests."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

ROOT=Path(__file__).resolve().parents[1]
DEPLOY=ROOT/'candidate/device-a6eed9e-v3-hca-r3-staged/deploy'
def load(name):
  s=importlib.util.spec_from_file_location('r3_'+name,DEPLOY/(name+'.py'))
  m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
hca=load('hca_timer_reset');runtime=load('pq46_runtime')


class StageTests(unittest.TestCase):
  def timer(self,age=0):
    t=hca.HcaTimerReset(quiet_s=.02);t.elapsed=round(age*50);return t
  def tick(self,t,**extra):
    return t.update(True,40,raw_torque=40,window_ok=True,continue_ok=True,
                    delayed_ok=True,notice_ready=True,**extra)
  def test_no_reset_before_180_then_complete55_and_new_cycle(self):
    t=self.timer()
    for _ in range(8999):self.assertTrue(self.tick(t)[1])
    self.assertEqual(self.tick(t),(0,False,False))
    for _ in range(53):self.assertEqual(self.tick(t),(0,False,False))
    self.assertEqual(self.tick(t),(0,False,True))
    self.assertEqual(t.completed,1);self.assertEqual(t.cycle,2);self.assertEqual(t.elapsed,0)
    self.assertTrue(self.tick(t)[1]);self.assertEqual(t.phase,'active')
  def test_notice_at_300_requires_ack_then_full_three_seconds(self):
    t=self.timer(299.98);self.assertTrue(self.tick(t)[1])
    self.assertEqual(t.phase,'awaiting_notice');self.assertTrue(t.notice_id)
    self.assertTrue(self.tick(t,notice_ack=True)[1]);self.assertEqual(t.phase,'countdown')
    for _ in range(149):self.assertTrue(self.tick(t)[1])
    self.assertEqual(self.tick(t),(0,False,False))
  def test_prediction_loss_cancels_reservation_without_pausing(self):
    t=self.timer(300);self.tick(t);self.tick(t,notice_ack=True)
    t.update(True,40,window_ok=True,continue_ok=True,delayed_ok=False,delayed_reason='future_turn_demand',notice_ready=True)
    self.assertFalse(t.standby);self.assertFalse(t.notice_id)
    self.assertEqual(t.notice_cancelled,1);self.assertEqual(t.last_abort_reason,'future_turn_demand')
  def test_no_audio_ack_cannot_silently_execute_late_pause(self):
    t=self.timer(300);self.tick(t)
    for _ in range(50):self.tick(t)
    self.assertFalse(t.standby);self.assertFalse(t.notice_id)
    self.assertEqual(t.last_abort_reason,'notice_not_delivered')
  def test_350_requests_takeover_without_unconditional_pause(self):
    t=self.timer(349.98)
    t.update(True,150,window_ok=False,continue_ok=False,delayed_ok=False)
    self.assertEqual(t.phase,'takeover_required');self.assertTrue(t.takeover_required)
    self.assertFalse(t.notice_id);self.assertFalse(t.standby)
    for _ in range(300):
      t.update(True,40,window_ok=True,continue_ok=True,delayed_ok=True,notice_ready=True)
      self.assertFalse(t.standby)
    self.assertEqual(t.completed,0);self.assertFalse(t.status()['forced_pause'])
  def test_notice_that_reaches_350_is_cancelled_and_cannot_execute(self):
    t=self.timer(349);t.notice_id='existing';t.notice_kind='reset';t.notice_acknowledged=True
    t.notice_ticks=t.notice_required-1
    t.elapsed=17499;out=self.tick(t)
    self.assertTrue(out[1]);self.assertFalse(t.standby);self.assertFalse(t.notice_id)
    self.assertTrue(t.takeover_required)
    self.assertEqual(t.last_abort_reason,'deadline')
  def test_single90_peak_no_longer_aborts_but_sustained_saturation_does(self):
    t=self.timer(180);self.tick(t)
    self.assertEqual(t.update(True,6,raw_torque=118,continue_ok=True),(0,False,False))
    for _ in range(9):self.assertEqual(t.update(True,6,raw_torque=280,continue_ok=True),(0,False,False))
    self.assertEqual(t.update(True,6,raw_torque=280,continue_ok=True),(6,True,False))
    self.assertEqual(t.last_abort_reason,'sustained_saturation');self.assertEqual(t.completed,0)
  def test_normal_pause_abort_stale_geometry_driver_and_native_disengage(self):
    for extra,reason in (({'continue_ok':False,'continue_reason':'model_stale'},'model_stale'),
                         ({'driver_input':True,'input_reason':'driver_steering'},'driver_steering')):
      t=self.timer(180);self.tick(t)
      out=t.update(True,6,raw_torque=40,**{'continue_ok':True,**extra})
      self.assertEqual(out,(6,True,False));self.assertEqual(t.last_abort_reason,reason)
    t=self.timer(300);self.tick(t);self.tick(t,notice_ack=True)
    for _ in range(150):self.tick(t)
    self.assertEqual(t.update(False,0),(0,False,False))
    self.assertEqual(t.last_abort_reason,'lateral_inactive')
  def test_clock_delay_counts_toward_350_without_forcing_pause(self):
    t=hca.HcaTimerReset(quiet_s=.02)
    t.update(True,40,now=100)
    t.update(True,40,now=450,window_ok=False)
    self.assertTrue(t.takeover_required);self.assertFalse(t.notice_id);self.assertFalse(t.standby)
  def test_three_second_notice_cannot_execute_fast_under_wall_clock(self):
    t=self.timer(300);self.tick(t,now=100);self.tick(t,notice_ack=True,now=100.1)
    for i in range(150):self.tick(t,now=100.1+(i+1)*.001)
    self.assertFalse(t.standby)
    self.assertEqual(self.tick(t,now=103.1),(0,False,False))
  def test_ui_loss_cancels_countdown_and_retains_control(self):
    t=self.timer(300);self.tick(t);self.tick(t,notice_ack=True)
    self.assertEqual(t.update(True,40,window_ok=True,delayed_ok=True,notice_ready=False),(40,True,False))
    self.assertFalse(t.notice_id);self.assertFalse(t.standby)
    self.assertEqual(t.last_abort_reason,'notice_ui_unavailable')
  def test_late_reset_completes55_and_starts_next_normal_cycle(self):
    t=self.timer(300);self.tick(t);self.tick(t,notice_ack=True)
    for _ in range(150):self.tick(t)
    for _ in range(53):self.tick(t)
    self.assertEqual(self.tick(t),(0,False,True))
    self.assertEqual(t.completed,1);self.assertEqual(t.elapsed,0);self.assertEqual(t.cycle,2)
    self.tick(t);self.assertEqual(t.phase,'active')


class GeometryTests(unittest.TestCase):
  def model(self):
    return NS(orientationRate=NS(t=[0,.5,1,1.5,2,2.5,3,3.5,4,4.5,5],z=[0]*11),
              laneLines=[NS(y=[0]),NS(y=[-1.8]),NS(y=[1.8])],
              laneLineProbs=[0,.95,.95],meta=NS(desireState=[1,0,0,0]))
  def test_delayed_window_can_accept_future_straight_after_current_curve(self):
    m=self.model();m.orientationRate.z[0:5]=[.03]*5
    self.assertFalse(runtime.geometry_gate(runtime.model_features(m,30))[0])
    self.assertTrue(runtime.geometry_gate(runtime.model_features(m,30,start_s=3))[0])
  def test_future_curve_and_missing_full_horizon_are_rejected(self):
    m=self.model();m.orientationRate.z[8]=.05
    self.assertFalse(runtime.geometry_gate(runtime.model_features(m,30,start_s=3))[0])
    m.orientationRate.t=m.orientationRate.t[:8];m.orientationRate.z=m.orientationRate.z[:8]
    self.assertEqual(runtime.model_features(m,30,start_s=3)['reason'],'prediction_missing')
  def test_countdown_window_moves_to_fixed_reserved_start(self):
    m=self.model();m.orientationRate.z[4]=.05
    self.assertTrue(runtime.geometry_gate(runtime.model_features(m,30,start_s=3))[0])
    self.assertFalse(runtime.geometry_gate(runtime.model_features(m,30,start_s=1))[0])


if __name__=='__main__':unittest.main()
