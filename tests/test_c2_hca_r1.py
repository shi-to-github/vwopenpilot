"""HCA r1 regression tests. Pure local execution; no vehicle connections."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / 'candidate/device-a6eed9e-v3-hca-r1/deploy'


def load(name):
  spec = importlib.util.spec_from_file_location('hca_r1_' + name, DEPLOY / (name + '.py'))
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


hca, runtime = load('hca_timer_reset'), load('pq46_runtime')


class TimerTest(unittest.TestCase):
  def ready(self, **kwargs):
    timer = hca.HcaTimerReset(seek_after_s=.1, quiet_s=.1, **kwargs)
    for _ in range(100):
      result = timer.update(True, 50, window_ok=True, continue_ok=True)
      if timer.standby:
        return timer, result
    self.fail('did not enter standby')

  def test_50_units_enters_and_80_unit_small_increase_completes_exact_100_frames(self):
    timer, first = self.ready()
    self.assertEqual(first, (0, False, False))
    for _ in range(98):
      self.assertEqual(timer.update(True, 6, raw_torque=80, window_ok=False,
        continue_ok=True), (0, False, False))
    self.assertEqual(timer.update(True, 6, raw_torque=80, window_ok=False,
      continue_ok=True), (0, False, True))
    self.assertEqual(timer.completed, 1)
    self.assertEqual(timer.elapsed, 0)
    self.assertEqual(timer.off_frames, 100)

  def test_mid_pause_actual_drift_large_raw_driver_and_stale_abort_without_reset(self):
    for extra, reason in (({'continue_ok': False, 'continue_reason': 'outward_center_motion'}, 'outward_center_motion'),
                          ({'raw_torque': 91}, 'large_raw_demand'),
                          ({'driver_input': True, 'input_reason': 'driver_steering'}, 'driver_steering'),
                          ({'continue_ok': False, 'continue_reason': 'model_stale'}, 'model_stale')):
      timer, _ = self.ready()
      before = timer.elapsed
      values = {'raw_torque': 50, 'window_ok': True, 'continue_ok': True, **extra}
      self.assertEqual(timer.update(True, 6, **values), (6, True, False))
      self.assertEqual(timer.elapsed, before + 1)
      self.assertEqual(timer.last_abort_reason, reason)
      self.assertEqual(timer.off_frames, 0)
      self.assertEqual(timer.completed, 0)

  def test_short_disengagement_does_not_clear_age_or_statistics(self):
    timer, _ = self.ready()
    age = timer.elapsed
    timer.update(False, 0)
    self.assertGreater(timer.elapsed, age)
    self.assertEqual(timer.aborted, 1)
    for _ in range(98):
      timer.update(False, 0)
    self.assertEqual(timer.elapsed, 0)
    self.assertEqual(timer.natural_resets, 1)
    self.assertEqual(timer.aborted, 1)
    for _ in range(500):
      timer.update(False, 0)
    self.assertEqual(timer.natural_resets, 1)
    self.assertEqual(timer.elapsed, 0)

  def test_short_inactive_gap_and_natural_zero_are_one_continuous_disabled_run(self):
    timer = hca.HcaTimerReset()
    for _ in range(1000): timer.update(True, 100)
    for _ in range(50): timer.update(False, 0)
    for _ in range(49): self.assertFalse(timer.update(True, 0)[2])
    self.assertTrue(timer.update(True, 0)[2])
    self.assertEqual(timer.elapsed, 0)

  def test_reengagement_interrupts_off_run_and_needs_new_100_frames(self):
    timer = hca.HcaTimerReset()
    for _ in range(1000): timer.update(True, 100)
    for _ in range(99): timer.update(False, 0)
    timer.update(True, 10)
    for _ in range(99): self.assertFalse(timer.update(False, 0)[2])
    self.assertTrue(timer.update(False, 0)[2])

  def test_cannot_start_pause_too_close_to_unchanged_deadline(self):
    timer = hca.HcaTimerReset(seek_after_s=.02, takeover_s=3)
    for _ in range(60): timer.update(True, 100)
    for _ in range(100): timer.update(True, 50, window_ok=True)
    self.assertEqual(timer.completed, 0)
    self.assertFalse(timer.standby)
    self.assertTrue(timer.takeover_required)

  def test_nonfinite_torque_outputs_no_invalid_command(self):
    timer, _ = self.ready()
    self.assertEqual(timer.update(True, float('nan'), raw_torque=float('nan'),
      continue_ok=True), (0, False, False))
    self.assertEqual(timer.last_abort_reason, 'nonfinite_torque')


def model(center=0):
  return NS(orientationRate=NS(t=[0, .5, 1, 2, 2.5, 3], z=[.001]*6),
            laneLines=[NS(y=[0]), NS(y=[-1.8+center]), NS(y=[1.8+center])],
            laneLineProbs=[0, .95, .95], meta=NS(desireState=[1, 0, 0, 0]))


class GeometryTest(unittest.TestCase):
  def test_center_hysteresis_and_large_deviation(self):
    features = runtime.model_features(model(.28), 30)
    self.assertFalse(runtime.motion_gate(features, 0, 2)[0])
    self.assertTrue(runtime.motion_gate(features, 0, 1, True)[0])
    self.assertFalse(runtime.motion_gate(runtime.model_features(model(.36), 30), 0, 1, True)[0])

  def test_predicted_outward_motion_aborts_before_boundary(self):
    features = runtime.model_features(model(.2), 30)
    self.assertEqual(runtime.motion_gate(features, .1, 2, True)[1], 'projected_center_margin')
    self.assertEqual(runtime.motion_gate(features, .2, .1, True)[1], 'outward_center_motion')
    self.assertTrue(runtime.motion_gate(features, -.1, 2, True)[0])

  def test_missing_history_invalid_curve_lanes_and_desire_are_not_relaxed(self):
    self.assertEqual(runtime.motion_gate(runtime.model_features(model(), 30), None, 2, True)[1], 'motion_history_missing')
    for change in ('curve', 'lanes', 'desire'):
      m = model()
      if change == 'curve': m.orientationRate.z[3] = .04
      elif change == 'lanes': m.laneLineProbs[1] = .5
      else: m.meta.desireState[1] = .2
      self.assertFalse(runtime.motion_gate(runtime.model_features(m, 30), 0, 2, True)[0])

  def test_history_only_advances_for_new_messages_and_resets_after_gap(self):
    from collections import deque
    r = runtime.Runtime.__new__(runtime.Runtime)
    r.history, r.last_model_ns, r.center_rate = deque(maxlen=12), 0, None
    for i in range(6): r.update_geometry(model(.001*i), round((10+i*.05)*1e9), 10+i*.05, 30, 2)
    self.assertTrue(r.window_ok)
    self.assertAlmostEqual(r.center_rate, .02)
    n = len(r.history)
    r.update_geometry(model(.005), r.last_model_ns, 10.26, 30, 2)
    self.assertEqual(len(r.history), n)
    r.update_geometry(model(), 11_000_000_000, 11, 30, 2)
    self.assertFalse(r.window_ok)
    self.assertIsNone(r.center_rate)


class IntegrationTest(unittest.TestCase):
  def fixture(self):
    import test_c2_v3_control as old
    tree = ast.parse((DEPLOY / 'carcontroller.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    controller, cc, cs = old.controller_fixture()
    ns = dict(old.controller_fixture.__globals__)
    ns.update(controller.__class__.__init__.__globals__)
    ns['HcaTimerReset'] = hca.HcaTimerReset
    exec(compile(ast.Module(body=[cls], type_ignores=[]), 'hca_r1_controller', 'exec'), ns)
    c = ns['CarController'](controller.CP.carFingerprint, controller.CP, None)
    c.pq_runtime.update = lambda speed, remaining=2: c.pq_runtime.now
    c.pq_runtime.continue_ok = True
    c.pq_runtime.window_reason = c.pq_runtime.continue_reason = 'quiet_prediction'
    # Actual rate limit stub: recovery must start at 6, not raw demand 150.
    c.update.__globals__['apply_std_steer_torque_limits'] = lambda new, last, driver, params: max(last-10, min(last+6, new))
    return c, cc, cs

  def test_abort_restores_rate_limited_output_and_preserves_no_cruise_default(self):
    c, cc, cs = self.fixture()
    c.pq_hca_timer_reset = hca.HcaTimerReset(seek_after_s=.02, quiet_s=.02)
    _, messages = c.update(cc, cs, 0)
    self.assertEqual(messages[0][2]['HCA_Status'], 3)
    cc.actuators.steer = .5
    c.frame = 2
    _, messages = c.update(cc, cs, 0)
    self.assertEqual(messages[0][2]['LM_Offset'], 6)
    self.assertEqual(c.pq_hca_timer_reset.last_abort_reason, 'large_raw_demand')
    self.assertFalse(any(m[0] == 'GRA_Neu' for m in messages))

  def test_driver_and_invalid_can_are_recorded_as_abort_reasons(self):
    for field, value, reason in (('steeringPressed', True, 'driver_steering'), ('canValid', False, 'can_invalid')):
      c, cc, cs = self.fixture()
      c.pq_hca_timer_reset = hca.HcaTimerReset(seek_after_s=.02, quiet_s=.02)
      c.update(cc, cs, 0)
      setattr(cs.out, field, value)
      c.frame = 2
      c.update(cc, cs, 0)
      self.assertEqual(c.pq_hca_timer_reset.last_abort_reason, reason)

  def test_existing_cruise_probe_sequence_is_unchanged(self):
    import test_c2_v3_control as old
    c, cc, cs = self.fixture()
    c.pq_runtime.mode = 'probe_down'
    sent = old.ControllerTest().run_frames(c, cc, cs, 600)
    gra = [(frame, msg[2]) for frame, msg in sent if msg[0] == 'GRA_Neu']
    self.assertEqual(len(gra), 10)
    self.assertEqual([g['GRA_Down_kurz'] for _, g in gra], [True]*9 + [False])
    self.assertEqual(gra[-1][0] - gra[0][0], 18)


if __name__ == '__main__':
  unittest.main()
