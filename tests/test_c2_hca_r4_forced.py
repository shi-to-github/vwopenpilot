"""R4 forced-fallback tests: 350 s prompt only, 355 s unconditional 1.1 s pause,
exactly 55 standby frames, and opportunistic statistics kept separate."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
DEPLOY=ROOT/'candidate/device-a6eed9e-v3-hca-r4-forced/deploy'
def load(name):
  s=importlib.util.spec_from_file_location('r4_'+name,DEPLOY/(name+'.py'))
  m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
hca=load('hca_timer_reset')


class ForcedFallbackTests(unittest.TestCase):
  def timer(self,age=0):
    t=hca.HcaTimerReset(quiet_s=.02);t.elapsed=round(age*50);return t
  def tick(self,t,**extra):
    return t.update(True,40,raw_torque=40,window_ok=True,continue_ok=True,
                    delayed_ok=True,notice_ready=True,**extra)

  def test_version_and_windows(self):
    t=self.timer()
    self.assertEqual(hca.VERSION,'hca-r4-forced')
    self.assertEqual((t.seek,t.warn,t.prompt,t.forced,t.backstop,t.required),(9000,15000,17500,17750,20000,55))

  def test_350_prompts_without_soft_disable_and_keeps_control(self):
    t=self.timer(349.98)
    self.assertEqual(self.tick(t),(40,True,False))
    self.assertEqual(t.phase,'forced_prompt')
    self.assertTrue(t.forced_prompt);self.assertTrue(t.prompt_id)
    self.assertEqual(t.forced_prompts,1)
    # The whole point of R4: the prompt must never request a soft disable.
    self.assertFalse(t.takeover_required)
    self.assertFalse(t.standby);self.assertFalse(t.forced_active)
    self.assertFalse(t.notice_id)
    self.assertEqual(t.start_block_reason,'insufficient_time_for_reset')

  def test_prompt_fires_once_per_cycle(self):
    t=self.timer(350);self.tick(t);self.tick(t)
    self.assertEqual(t.forced_prompts,1)
    for _ in range(100):self.tick(t)
    self.assertEqual(t.forced_prompts,1);self.assertFalse(t.takeover_required)

  def test_355_forces_pause_despite_every_gate(self):
    t=self.timer(354.98)
    out=t.update(True,150,raw_torque=150,window_ok=False,continue_ok=False,
                 delayed_ok=False,driver_input=True,notice_ready=True)
    self.assertEqual(out,(0,False,False))
    self.assertTrue(t.forced_active);self.assertEqual(t.standby,1)
    self.assertEqual(t.phase,'forced_standby')

  def test_forced_pause_is_exactly_55_frames_then_resets_local_timer(self):
    t=self.timer(354.98)
    self.assertEqual(t.update(True,150,window_ok=False,driver_input=True),(0,False,False))
    for _ in range(53):self.assertEqual(self.tick(t),(0,False,False))
    self.assertTrue(t.forced_active);self.assertEqual(t.standby,54)
    self.assertEqual(self.tick(t),(0,False,True))
    self.assertEqual(t.forced_completed,1);self.assertEqual(t.forced_aborted,0)
    self.assertEqual(t.completed,0);self.assertEqual(t.aborted,0)
    self.assertEqual(t.cycle,2);self.assertEqual(t.elapsed,0)
    self.assertFalse(t.forced_active);self.assertEqual(t.phase,'forced_reset_complete')
    self.assertEqual(self.tick(t),(40,True,False));self.assertEqual(t.phase,'active')

  def test_forced_pause_counts_frames_even_when_last_command_was_zero_torque(self):
    t=self.timer(180)
    self.assertEqual(t.update(True,0,raw_torque=0,window_ok=True,continue_ok=True),(0,False,False))
    self.assertTrue(t.standby);self.assertFalse(t.forced_active)
    frames=1
    while True:
      frames+=1
      if self.tick(t)[2]:break
    self.assertEqual(frames,55);self.assertEqual(t.completed,1)

  def test_forced_pause_ignores_driver_input_saturation_and_dead_geometry(self):
    t=self.timer(354.98)
    t.update(True,150,window_ok=False,driver_input=True)
    for _ in range(20):
      out=t.update(True,290,raw_torque=295,window_ok=False,continue_ok=False,
                   delayed_ok=False,driver_input=True,notice_ready=False)
      self.assertFalse(out[1])
    self.assertTrue(t.forced_active);self.assertEqual(t.phase,'forced_standby')
    self.assertEqual(t.forced_aborted,0);self.assertEqual(t.aborted,0)

  def test_only_a_real_disengage_aborts_the_forced_pause(self):
    t=self.timer(354.98)
    t.update(True,150,window_ok=False,driver_input=True)
    self.tick(t);self.assertTrue(t.forced_active)
    self.assertEqual(t.update(False,0),(0,False,False))
    self.assertEqual(t.forced_aborted,1);self.assertEqual(t.aborted,0)
    self.assertEqual(t.standby,0);self.assertFalse(t.forced_active)
    self.assertEqual(t.last_abort_reason,'lateral_inactive')
    # A disengage is reported as inactive; the counter records the lost sample.
    self.assertEqual(t.phase,'inactive')

  def test_forced_cycle_keeps_soft_disable_off_until_backstop(self):
    t=self.timer(354.98)
    t.update(True,150,window_ok=False,driver_input=True)
    for _ in range(54):
      self.tick(t)
      self.assertFalse(t.takeover_required)
    self.tick(t)
    self.assertFalse(t.takeover_required)
    self.assertEqual(t.backstop,20000)
    self.assertEqual(t.status()['takeover_after_s'],400.0)

  def test_clock_jump_into_prompt_then_into_forced_window(self):
    t=hca.HcaTimerReset(quiet_s=.02)
    t.update(True,40,now=100)
    self.assertEqual(t.update(True,40,now=450,window_ok=False)[1],True)
    self.assertTrue(t.forced_prompt);self.assertFalse(t.takeover_required)
    self.assertFalse(t.standby)
    self.assertEqual(t.update(True,40,now=460,window_ok=False),(0,False,False))
    self.assertTrue(t.forced_active)

  def test_opportunistic_path_is_unchanged_and_kept_separate(self):
    t=self.timer(180)
    self.assertEqual(self.tick(t),(0,False,False))
    self.assertTrue(t.standby);self.assertFalse(t.forced_active)
    self.assertEqual(t.phase,'standby')
    for _ in range(53):self.assertEqual(self.tick(t),(0,False,False))
    self.assertEqual(self.tick(t),(0,False,True))
    self.assertEqual(t.completed,1);self.assertEqual(t.forced_completed,0)
    self.assertEqual(t.cycle,2)

  def test_opportunistic_abort_still_uses_the_normal_counters(self):
    t=self.timer(180);self.tick(t)
    self.assertEqual(t.update(True,6,raw_torque=40,continue_ok=False,continue_reason='model_stale'),(6,True,False))
    self.assertEqual(t.aborted,1);self.assertEqual(t.forced_aborted,0)
    self.assertEqual(t.last_abort_reason,'model_stale')

  def test_late_notice_flow_and_ack_requirement_are_unchanged(self):
    t=self.timer(299.98);self.assertTrue(self.tick(t)[1])
    self.assertEqual(t.phase,'awaiting_notice');self.assertTrue(t.notice_id)
    self.assertTrue(self.tick(t,notice_ack=True)[1]);self.assertEqual(t.phase,'countdown')
    for _ in range(149):self.assertTrue(self.tick(t)[1])
    self.assertEqual(self.tick(t),(0,False,False))
    self.assertTrue(t.standby);self.assertFalse(t.forced_active)

  def test_reservation_window_closes_before_the_prompt(self):
    t=self.timer(344)
    self.assertEqual(self.tick(t),(40,True,False))
    self.assertTrue(t.notice_id);self.assertEqual(t.phase,'awaiting_notice')
    t=self.timer(345)
    self.tick(t)
    self.assertFalse(t.notice_id)
    self.assertEqual(t.start_block_reason,'insufficient_time_for_reset')

  def test_forced_pause_runs_even_when_the_ui_never_acknowledges(self):
    t=self.timer(344);self.tick(t)
    self.assertTrue(t.notice_id)
    for _ in range(50):self.tick(t)
    self.assertFalse(t.notice_id)
    self.assertEqual(t.last_abort_reason,'notice_not_delivered')
    t.elapsed=17749
    out=self.tick(t)
    self.assertEqual(out[1],False)
    self.assertTrue(t.forced_active)
    self.assertEqual(t.phase,'forced_standby')


if __name__=='__main__':unittest.main()
