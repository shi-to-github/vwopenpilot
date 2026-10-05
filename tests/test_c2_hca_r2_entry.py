"""R2 entry filtering, unchanged immediate aborts and disabled-frame accounting."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
def load(path, name):
  spec=importlib.util.spec_from_file_location(name,ROOT/path)
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  return module
r2=load('candidate/device-a6eed9e-v3-hca-r2-entry/deploy/hca_timer_reset.py','entry_r2')
r1=load('candidate/device-a6eed9e-v3-hca-r1/deploy/hca_timer_reset.py','entry_r1')


class EntryTests(unittest.TestCase):
  def ready(self):
    timer=r2.HcaTimerReset(seek_after_s=.02)
    for _ in range(100):
      out=timer.update(True,40,window_ok=True,continue_ok=True)
      if timer.standby:return timer,out
    self.fail('no standby')

  def test_brief_moderate_spikes_preserve_evidence_but_start_instantaneously_low(self):
    old=r1.HcaTimerReset(seek_after_s=.02)
    new=r2.HcaTimerReset(seek_after_s=.02)
    began=False
    for i in range(200):
      request=80 if i%8==0 else 40
      old.update(True,request,window_ok=True,continue_ok=True)
      new.update(True,request,window_ok=True,continue_ok=True)
      if new.standby:
        self.assertLessEqual(request,60);began=True;break
    self.assertTrue(began)
    self.assertFalse(old.standby)

  def test_rms_uses_squared_magnitude_and_rejects_sustained_signed_load(self):
    timer=r2.HcaTimerReset(seek_after_s=.02)
    for i in range(200):timer.update(True,70 if i%2 else -70,window_ok=True)
    self.assertFalse(timer.standby)
    self.assertAlmostEqual(timer.entry_raw_rms,70)

  def test_large_peak_does_not_get_averaged_away(self):
    timer=r2.HcaTimerReset(seek_after_s=.02)
    for _ in range(30):timer.update(True,40,window_ok=True)
    timer.update(True,6,raw_torque=91,window_ok=True)
    self.assertEqual(timer.start_block_reason,'entry_peak_above_abort')
    self.assertEqual(timer.quiet,0)
    self.assertFalse(timer.standby)

  def test_current_80_cannot_start_even_after_quiet_evidence_is_confirmed(self):
    timer=r2.HcaTimerReset(seek_after_s=.02,quiet_s=1)
    for _ in range(20):timer.update(True,40,window_ok=True)
    timer.quiet=timer.quiet_required-1
    result=timer.update(True,80,window_ok=True)
    self.assertTrue(result[1]);self.assertFalse(timer.standby)
    self.assertEqual(timer.start_block_reason,'waiting_instantaneous_low_torque')

  def test_geometry_loss_resets_confirmation_and_driver_clears_torque_history(self):
    for extra in ({'window_ok':False},{'driver_input':True}):
      timer=r2.HcaTimerReset(seek_after_s=.02)
      for _ in range(30):timer.update(True,40,window_ok=True)
      timer.update(True,40,**{'window_ok':True,**extra})
      self.assertEqual(timer.quiet,0)
      if extra.get('driver_input'):self.assertFalse(timer.entry_history)

  def test_full_pause_is_still_exactly_100_disabled_frames(self):
    timer,first=self.ready();self.assertEqual(first,(0,False,False))
    for _ in range(98):self.assertEqual(timer.update(True,6,raw_torque=80,continue_ok=True),(0,False,False))
    self.assertEqual(timer.update(True,6,raw_torque=80,continue_ok=True),(0,False,True))
    self.assertEqual(timer.completed,1);self.assertEqual(timer.elapsed,0)

  def test_immediate_abort_on_large_request_driver_curve_or_stale_is_unchanged(self):
    for extra,reason in (({'raw_torque':91},'large_raw_demand'),
                         ({'driver_input':True,'input_reason':'driver_steering'},'driver_steering'),
                         ({'continue_ok':False,'continue_reason':'future_turn_demand'},'future_turn_demand'),
                         ({'continue_ok':False,'continue_reason':'model_stale'},'model_stale')):
      timer,_=self.ready();age=timer.elapsed
      result=timer.update(True,6,**{'raw_torque':40,'continue_ok':True,**extra})
      self.assertEqual(result,(6,True,False));self.assertEqual(timer.last_abort_reason,reason)
      self.assertEqual(timer.elapsed,age+1);self.assertEqual(timer.completed,0)
      self.assertFalse(timer.entry_history)

  def test_nonfinite_and_short_inactive_do_not_confirm_reset(self):
    timer,_=self.ready();age=timer.elapsed
    self.assertEqual(timer.update(True,float('nan'),continue_ok=True),(0,False,False))
    self.assertEqual(timer.last_abort_reason,'nonfinite_torque')
    self.assertGreater(timer.elapsed,age);self.assertEqual(timer.completed,0)
    for _ in range(98):timer.update(False,0)
    self.assertEqual(timer.natural_resets,1);self.assertEqual(timer.elapsed,0)

  def test_search_begins_150s_but_no_pause_can_cross_240s_deadline(self):
    timer=r2.HcaTimerReset()
    self.assertEqual(timer.seek,7500);self.assertEqual(timer.deadline,12000)
    timer.elapsed=11900
    for _ in range(150):timer.update(True,40,window_ok=True)
    self.assertFalse(timer.standby);self.assertEqual(timer.completed,0)
    self.assertTrue(timer.takeover_required)

  def test_abort_restore_still_uses_controller_rate_limit(self):
    import test_c2_hca_r1 as old
    c,cc,cs=old.IntegrationTest().fixture()
    c.pq_hca_timer_reset=r2.HcaTimerReset(seek_after_s=.02,quiet_s=.02,entry_window_s=.02)
    _,sent=c.update(cc,cs,0);self.assertEqual(sent[0][2]['HCA_Status'],3)
    cc.actuators.steer=.5;c.frame=2
    _,sent=c.update(cc,cs,0);self.assertEqual(sent[0][2]['LM_Offset'],6)
    self.assertEqual(c.pq_hca_timer_reset.last_abort_reason,'large_raw_demand')
    self.assertFalse(any(m[0]=='GRA_Neu' for m in sent))


if __name__=='__main__':unittest.main()
