"""Offline state-machine and exact-controller tests; no connection to a car."""
import ast
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest

DEPLOY = Path(__file__).resolve().parents[1] / 'candidate/device-a6eed9e-v3/deploy'


def load(name):
  spec = importlib.util.spec_from_file_location('v3_' + name, DEPLOY / (name + '.py'))
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


hca = load('hca_timer_reset')
cruise = load('pq46_cruise')
runtime = load('pq46_runtime')
pqcan = load('pqcan')


def good_model():
  return NS(orientationRate=NS(t=[0, 0.5, 1, 2, 2.5, 3], z=[0.001] * 6),
            laneLines=[NS(y=[0]), NS(y=[-1.8]), NS(y=[1.8])],
            laneLineProbs=[0, .95, .95], meta=NS(desireState=[1, 0, 0, 0]))


class HcaTest(unittest.TestCase):
  def test_three_minutes_then_exact_100_frame_standby(self):
    timer = hca.HcaTimerReset()
    zero_frames, completions = [], []
    for frame in range(9200):
      torque, enabled, completed = timer.update(True, 10, window_ok=True)
      if not enabled:
        zero_frames.append(frame)
      if completed:
        completions.append(frame)
      if frame < 8999:
        self.assertEqual(torque, 10)
    self.assertEqual(len(zero_frames), 100)
    self.assertEqual(zero_frames, list(range(zero_frames[0], zero_frames[0] + 100)))
    self.assertEqual(completions, [zero_frames[-1]])
    self.assertGreaterEqual(zero_frames[0], 9000)

  def test_future_demand_aborts_immediately_without_resetting_age(self):
    timer = hca.HcaTimerReset(seek_after_s=1, quiet_s=.1)
    while not timer.standby:
      timer.update(True, 10, window_ok=True)
    age = timer.elapsed
    self.assertEqual(timer.update(True, 150, raw_torque=150, window_ok=False), (150, True, False))
    self.assertEqual(timer.elapsed, age + 1)
    self.assertEqual(timer.aborted, 1)
    self.assertEqual(timer.completed, 0)
    for _ in range(249):
      self.assertTrue(timer.update(True, 10, window_ok=True)[1])
    timer.update(True, 10, window_ok=True)
    self.assertTrue(timer.standby)

  def test_raw_demand_prevents_window_despite_limited_torque(self):
    timer = hca.HcaTimerReset(seek_after_s=1)
    for _ in range(500):
      self.assertTrue(timer.update(True, 10, raw_torque=100, window_ok=True)[1])
    self.assertFalse(timer.standby)

  def test_missing_prediction_never_forces_pause_at_deadline(self):
    timer = hca.HcaTimerReset(seek_after_s=1, takeover_s=3)
    for _ in range(151):
      self.assertEqual(timer.update(True, 50), (50, True, False))
    self.assertTrue(timer.takeover_required)
    timer.update(False, 0)
    self.assertFalse(timer.takeover_required)

  def test_natural_two_second_standby_resets_age(self):
    timer = hca.HcaTimerReset()
    for _ in range(500):
      timer.update(True, 10)
    for _ in range(99):
      self.assertFalse(timer.update(True, 0)[2])
    self.assertTrue(timer.update(True, 0)[2])
    self.assertEqual(timer.elapsed, 0)

  def test_driver_input_aborts_pause(self):
    timer = hca.HcaTimerReset(seek_after_s=.02, quiet_s=.02)
    timer.update(True, 10, window_ok=True)
    self.assertTrue(timer.standby)
    self.assertEqual(timer.update(True, 10, window_ok=True, driver_input=True), (10, True, False))


class ModelTest(unittest.TestCase):
  def test_quiet_prediction(self):
    self.assertTrue(runtime.model_window(good_model(), 30)[0])

  def test_future_curve_and_bad_center(self):
    model = good_model()
    model.orientationRate.z[3] = .04
    self.assertEqual(runtime.model_window(model, 30)[1], 'future_turn_demand')
    model = good_model()
    model.laneLines[2].y = [2.5]
    self.assertEqual(runtime.model_window(model, 30)[1], 'lane_center_error')

  def test_nan_timestamps_missing_desire_and_nonmonotonic_prediction(self):
    for field in ('nan', 'nonmonotonic', 'missing_desire'):
      model = good_model()
      if field == 'nan':
        model.orientationRate.t[1] = float('nan')
      elif field == 'nonmonotonic':
        model.orientationRate.t[2] = 0.1
      else:
        model.meta.desireState = []
      self.assertFalse(runtime.model_window(model, 30)[0])

  def test_mode_heartbeat_expiry_and_future_clock(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / 'mode.json'
      path.write_text(json.dumps({'mode': 'auto', 'boot_s': 10}), encoding='utf-8')
      self.assertEqual(runtime.requested_mode(12, path), 'auto')
      self.assertEqual(runtime.requested_mode(14, path), 'base')
      self.assertEqual(runtime.requested_mode(9, path), 'base')


class PulseTest(unittest.TestCase):
  def pulse(self, direction='down'):
    pulse = cruise.ButtonPulse()
    self.assertTrue(pulse.start(direction, 99.84, 0))
    return pulse

  def test_nine_native_slots_then_release_and_no_retry(self):
    pulse = self.pulse()
    actions = [pulse.frame(index * .02) for index in range(10)]
    self.assertEqual(actions, ['down'] * 9 + ['release'])
    pulse.update(2.18, 99.84, True)
    self.assertEqual(pulse.phase, 'fault')
    self.assertEqual(pulse.reason, 'ecu_ack_timeout')
    self.assertEqual(pulse.frame(3), '')

  def test_expected_readback_stops_press_early_then_ack(self):
    pulse = self.pulse()
    self.assertEqual(pulse.frame(0), 'down')
    pulse.update(.05, 89.6, True)
    self.assertEqual(pulse.frame(.06), 'release')
    pulse.update(.07, 89.6, True)
    self.assertEqual(pulse.phase, 'done')

  def test_wrong_direction_or_multiple_steps_fault(self):
    for target, reason in ((110.08, 'wrong_direction'), (79.36, 'unexpected_step')):
      pulse = self.pulse()
      pulse.frame(0)
      pulse.update(.05, target, True)
      self.assertEqual(pulse.reason, reason)
      self.assertEqual(pulse.frame(.06), '')

  def test_stale_feedback_and_driver_override_stop(self):
    for allow, driver, expected in ((False, False, 'controls_or_feedback_unavailable'),
                                     (True, True, 'driver_override')):
      pulse = self.pulse()
      pulse.update(.1, 99.84, allow, driver)
      self.assertEqual(pulse.reason, expected)

  def test_missing_native_slots_timeout(self):
    pulse = self.pulse()
    pulse.update(.81, 99.84, True)
    self.assertEqual(pulse.reason, 'native_counter_or_release_timeout')


LEAD = {'status': True, 'distance': 90., 'lateral': 0., 'relative': -5.,
        'speed': 25., 'prob': .95}
CLEAR = {**LEAD, 'status': False}


def trim_ready(mode='auto', lead=LEAD):
  trim = cruise.CruiseTrim()
  trim.set_mode(mode)
  trim.update(0, True, 120.32, 120, data_fresh=True, lead=lead)
  trim.update(5, True, 120.32, 120, data_fresh=True, lead=lead)
  trim.update(7, True, 120.32, 120, data_fresh=True, lead=lead)
  return trim


def acknowledge(trim, target, start=7):
  trim.pulse.frame(start)
  trim.update(start + .05, True, target, 110, data_fresh=True, lead=LEAD)
  trim.pulse.frame(start + .06)
  trim.update(start + .07, True, target, 110, data_fresh=True, lead=LEAD)


class TrimTest(unittest.TestCase):
  def test_base_has_no_commands(self):
    trim = trim_ready('base')
    self.assertEqual(trim.pulse.phase, 'idle')

  def test_lead_trim_and_clear_restore_ceiling(self):
    trim = trim_ready()
    self.assertEqual(trim.pulse.direction, 'down')
    self.assertEqual(trim.ceiling, 120.32)
    acknowledge(trim, 110.08)
    trim.update(10, True, 110.08, 110, data_fresh=True, lead=CLEAR)
    trim.update(13, True, 110.08, 110, data_fresh=True, lead=CLEAR)
    self.assertEqual(trim.pulse.direction, 'recall')
    self.assertEqual(trim.ceiling, 120.32)
    self.assertEqual(trim.desired, 120.32)

  def test_ack_timeout_stops_without_retry_and_mode_toggle_cannot_clear(self):
    trim = trim_ready()
    for index in range(10):
      trim.pulse.frame(7 + index * .02)
    trim.update(9.2, True, 120.32, 120, data_fresh=True, lead=LEAD)
    self.assertEqual(trim.fault, 'ecu_ack_timeout')
    trim.set_mode('base')
    trim.set_mode('auto')
    trim.update(20, True, 120.32, 120, data_fresh=True, lead=LEAD)
    self.assertEqual(trim.fault, 'ecu_ack_timeout')
    self.assertEqual(trim.pulse.phase, 'idle')
    trim.update(21, False, 120.32, 120)
    self.assertEqual(trim.fault, '')

  def test_missing_or_uncertain_lead_does_not_restore(self):
    for fresh, lead in ((False, CLEAR), (True, {**LEAD, 'prob': .5}),
                         (True, {**LEAD, 'distance': float('nan')})):
      trim = trim_ready()
      acknowledge(trim, 110.08)
      for now in (10, 20, 30):
        trim.update(now, True, 110.08, 110, data_fresh=fresh, lead=lead)
      self.assertEqual(trim.pulse.phase, 'idle')
      self.assertLess(trim.desired, trim.ceiling)

  def test_manual_handle_recaptures_ceiling(self):
    trim = trim_ready('base')
    trim.update(8, True, 99.84, 100, driver_button=True)
    trim.update(9, True, 99.84, 100)
    self.assertEqual(trim.ceiling, 120.32)
    trim.update(10.1, True, 99.84, 100)
    self.assertEqual(trim.ceiling, 99.84)

  def test_speed_guard_and_hca_reset_do_not_send(self):
    for options in ({'speed': 60}, {'steer_reset': True}, {'gas': True}, {'brake': True}):
      trim = cruise.CruiseTrim()
      trim.set_mode('probe_down')
      for now in (0, 6, 12):
        arguments = {'speed': 100, **options}
        trim.update(now, True, 99.84, **arguments)
      self.assertEqual(trim.pulse.phase, 'idle')

  def test_no_coarse_step_below_floor_or_restore_over_ceiling(self):
    trim = cruise.CruiseTrim()
    trim.set_mode('auto')
    for now in (0, 5, 7):
      trim.update(now, True, 69.12, 72, data_fresh=True, lead={**LEAD, 'speed': 10.})
    self.assertEqual(trim.pulse.phase, 'idle')
    trim.ceiling = trim.desired = trim.last_target = 69.12
    for now in (10, 13, 20):
      trim.update(now, True, 69.12, 72, data_fresh=True, lead=CLEAR)
    self.assertEqual(trim.pulse.phase, 'idle')

  def test_remaining_gap_cannot_fit_fine_step_so_no_restore_press(self):
    trim = cruise.CruiseTrim()
    trim.set_mode('auto')
    for now in (0, 5, 8):
      trim.update(now, True, 120.32, 120, data_fresh=True, lead=CLEAR)
    trim.ceiling = trim.desired = 121.6
    trim.update(10, True, 120.32, 120, data_fresh=True, lead=CLEAR)
    self.assertEqual(trim.pulse.phase, 'idle')

  def test_out_of_bounds_readback_stops_the_command(self):
    pulse = cruise.ButtonPulse()
    pulse.start('recall', 99.84, 0, minimum=60, maximum=101.12)
    pulse.frame(0)
    pulse.update(.05, 102.4, True)
    self.assertEqual(pulse.reason, 'target_limit_exceeded')


class FakeRuntime:
  def __init__(self):
    self.now = 0
    self.mode = 'base'
    self.window_ok = True
    self.lead_fresh = True
    self.lead = LEAD.copy()
  def update(self, speed):
    return self.now
  def write_status(self, *args):
    pass


def controller_fixture():
  tree = ast.parse((DEPLOY / 'carcontroller.py').read_text(encoding='utf-8'))
  node = next(node for node in tree.body if isinstance(node, ast.ClassDef))
  ns = {'CANPacker': lambda dbc: NS(make_can_msg=lambda name, bus, values: (name, bus, values)),
        'CarControllerParams': lambda cp: NS(HCA_STEP=2, STEER_MAX=300,
          ACC_CONTROL_STEP=100000, LDW_STEP=100000, ACC_HUD_STEP=100000),
        'PQ_CARS': {'pq'}, 'pqcan': pqcan, 'mqbcan': pqcan, 'HcaTimerReset': hca.HcaTimerReset,
        'CruiseTrim': cruise.CruiseTrim, 'Runtime': FakeRuntime, 'CANBUS': NS(pt=0),
        'VisualAlert': NS(steerRequired=1, ldw=2), 'CV': NS(MS_TO_KPH=3.6),
        'apply_std_steer_torque_limits': lambda new, last, driver, params: new}
  exec(compile(ast.Module(body=[node], type_ignores=[]), 'v3_controller', 'exec'), ns)
  cp = NS(carFingerprint='pq', pcmCruise=True, openpilotLongitudinalControl=False)
  controller = ns['CarController']('unused', cp, None)
  actuators = NS(steer=.03)
  actuators.copy = lambda: NS(steer=actuators.steer)
  cc = NS(actuators=actuators, hudControl=NS(visualAlert=0, leftLaneDepart=False,
          leftLaneVisible=True, rightLaneDepart=False, rightLaneVisible=True),
          cruiseControl=NS(cancel=False, resume=False), latActive=True, enabled=True)
  cs = NS(out=NS(steeringTorque=0, steeringPressed=False, canValid=True,
          leftBlinker=False, rightBlinker=False, brakePressed=False, gasPressed=False,
          vEgo=100/3.6, cruiseState=NS(enabled=True, speed=99.84/3.6)),
          gra_stock_values={name: 0 for name in ('COUNTER', 'GRA_Abbrechen', 'GRA_Neu_Setzen',
            'GRA_Up_lang', 'GRA_Down_lang', 'GRA_Up_kurz', 'GRA_Down_kurz', 'GRA_Recall', 'GRA_Zeitluecke')},
          ldw_stock_values={}, pq_motor_target_kph=99.84, pq_motor_target_fresh=True, pq_gra_fresh=True)
  return controller, cc, cs


class ControllerTest(unittest.TestCase):
  def run_frames(self, controller, cc, cs, count, start=0):
    sent = []
    for frame in range(start, start + count):
      controller.pq_runtime.now = frame * .01
      cs.gra_stock_values['COUNTER'] = frame // 2 % 16
      _, messages = controller.update(cc, cs, 0)
      sent += [(frame, msg) for msg in messages]
    return sent

  def test_probe_exact_native_counter_slots_and_180ms_release(self):
    controller, cc, cs = controller_fixture()
    controller.pq_runtime.mode = 'probe_down'
    sent = self.run_frames(controller, cc, cs, 600)
    gra = [(frame, msg[2]) for frame, msg in sent if msg[0] == 'GRA_Neu']
    self.assertEqual(len(gra), 10)
    self.assertEqual([g['GRA_Down_kurz'] for _, g in gra], [True] * 9 + [False])
    self.assertEqual(gra[-1][0] - gra[0][0], 18)
    self.assertEqual([g['COUNTER'] for _, g in gra], [((f//2)+1)%16 for f, _ in gra])
    for _, g in gra:
      self.assertFalse(g['GRA_Up_kurz'])
      self.assertFalse(g['GRA_Recall'])
    self.run_frames(controller, cc, cs, 300, 600)
    self.assertEqual(controller.pq_cruise.fault, 'ecu_ack_timeout')

  def test_default_and_stale_motor_feedback_do_not_inject(self):
    for mode, fresh in (('base', True), ('probe_up', False)):
      controller, cc, cs = controller_fixture()
      controller.pq_runtime.mode = mode
      cs.pq_motor_target_fresh = fresh
      sent = self.run_frames(controller, cc, cs, 700)
      self.assertFalse(any(msg[0] == 'GRA_Neu' for _, msg in sent))

  def test_real_handle_has_precedence(self):
    controller, cc, cs = controller_fixture()
    controller.pq_runtime.mode = 'probe_down'
    cs.gra_stock_values['GRA_Recall'] = True
    sent = self.run_frames(controller, cc, cs, 700)
    self.assertFalse(any(msg[0] == 'GRA_Neu' for _, msg in sent))

  def test_quiet_pause_and_immediate_restore_from_raw_steer(self):
    controller, cc, cs = controller_fixture()
    controller.pq_hca_timer_reset = hca.HcaTimerReset(seek_after_s=.02, quiet_s=.02)
    _, sent = controller.update(cc, cs, 0)
    self.assertEqual(sent[0][2]['HCA_Status'], 3)
    cc.actuators.steer = .5
    controller.frame = 2
    _, sent = controller.update(cc, cs, 0)
    self.assertEqual(sent[0][2]['LM_Offset'], 150)
    self.assertEqual(controller.pq_hca_timer_reset.aborted, 1)


if __name__ == '__main__':
  unittest.main()
