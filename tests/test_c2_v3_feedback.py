"""Execute the actual PQ parser and interface methods with schema stubs."""
import ast
from collections import defaultdict
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / 'candidate/device-a6eed9e-v3/deploy'


def method(filename, name, namespace):
  tree = ast.parse((DEPLOY / filename).read_text(encoding='utf-8'))
  cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
  node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
  node.decorator_list = []
  exec(compile(ast.Module(body=[node], type_ignores=[]), filename, 'exec'), namespace)
  return namespace[name]


class FeedbackTest(unittest.TestCase):
  def fixture(self, age=0):
    ret = NS(cruiseState=NS(speed=0, available=False, enabled=False))
    namespace = {'car': NS(CarState=NS(new_message=lambda: ret)),
      'CV': NS(KPH_TO_MS=1/3.6, DEG_TO_RAD=.01745), 'sec_since_boot': lambda: 10,
      'TransmissionType': NS(automatic=1, manual=2),
      'GearShifter': NS(drive=1, reverse=2), 'NetworkLocation': NS(fwdCamera=1)}
    update = method('carstate.py', 'update_pq', namespace)
    cp = NS(vl=defaultdict(lambda: defaultdict(float)),
            ts_nanos={'Motor_2': {'Soll_Geschwindigkeit_bei_GRA_Be': (10-age)*1e9},
                      'GRA_Neu': {'COUNTER': (10-age)*1e9}})
    cp.vl['Bremse_1']['Geschwindigkeit_neu__Bremse_1_'] = 80
    cp.vl['Motor_2']['GRA_Status'] = 1
    cp.vl['Motor_2']['Soll_Geschwindigkeit_bei_GRA_Be'] = 99.84
    state = NS(CP=NS(enableBsm=False, networkLocation=0, pcmCruise=True),
      CCP=NS(STEER_DRIVER_ALLOWANCE=80, hca_status_values={}, BUTTONS=[]),
      get_wheel_speeds=lambda *args: args, update_speed_kf=lambda speed: (speed, 0),
      update_blinker_from_stalk=lambda *args: (False, False), create_button_events=lambda *args: [])
    return update, state, cp, ret

  def test_engine_target_is_used_without_changing_real_car_speed(self):
    update, state, cp, _ = self.fixture()
    ret = update(state, cp, cp, cp, 0)
    self.assertAlmostEqual(ret.cruiseState.speed * 3.6, 99.84)
    self.assertAlmostEqual(ret.vEgo * 3.6, 80)
    self.assertTrue(state.pq_motor_target_fresh)
    self.assertTrue(state.pq_gra_fresh)

  def test_stale_or_missing_timestamp_never_infers_target_from_speed(self):
    for missing in (False, True):
      update, state, cp, _ = self.fixture(.16)
      if missing:
        del cp.ts_nanos
      ret = update(state, cp, cp, cp, 0)
      self.assertEqual(ret.cruiseState.speed, 0)
      self.assertFalse(state.pq_motor_target_fresh)

  def test_valid_acc_display_target_retains_priority(self):
    update, state, cp, _ = self.fixture()
    cp.vl['ACC_GRA_Anziege']['ACA_V_Wunsch'] = 110
    ret = update(state, cp, cp, cp, 0)
    self.assertAlmostEqual(ret.cruiseState.speed * 3.6, 110)

  def test_old_compiled_parser_uses_current_batch_receipts_and_expires(self):
    update, state, cp, _ = self.fixture()
    del cp.ts_nanos
    cp.vl_all = {'Motor_2': {'Soll_Geschwindigkeit_bei_GRA_Be': [99.84]},
                 'GRA_Neu': {'COUNTER': [0]}}
    ret = update(state, cp, cp, cp, 0)
    self.assertTrue(state.pq_motor_target_fresh)
    self.assertTrue(state.pq_gra_fresh)
    self.assertAlmostEqual(ret.cruiseState.speed * 3.6, 99.84)
    cp.vl_all = {'Motor_2': {}, 'GRA_Neu': {}}
    update.__globals__['sec_since_boot'] = lambda: 10.1
    update(state, cp, cp, cp, 0)
    self.assertTrue(state.pq_motor_target_fresh)
    update.__globals__['sec_since_boot'] = lambda: 10.16
    ret = update(state, cp, cp, cp, 0)
    self.assertFalse(state.pq_motor_target_fresh)
    self.assertFalse(state.pq_gra_fresh)
    self.assertEqual(ret.cruiseState.speed, 0)

  def test_parser_requests_the_target_and_counter_in_existing_50hz_frames(self):
    namespace = {'DBC': {'pq': {'pt': 'vw'}}, 'CANBUS': NS(pt=0),
      'TransmissionType': NS(automatic=1, manual=2),
      'NetworkLocation': NS(fwdCamera=1),
      'CANParser': lambda dbc, signals, checks, bus: (signals, checks)}
    parser = method('carstate.py', 'get_can_parser_pq', namespace)
    signals, checks = parser(NS(carFingerprint='pq', transmissionType=0, enableBsm=False, networkLocation=0))
    self.assertIn(('Soll_Geschwindigkeit_bei_GRA_Be', 'Motor_2'), signals)
    self.assertIn(('COUNTER', 'GRA_Neu'), signals)
    self.assertIn(('Motor_2', 50), checks)
    self.assertIn(('GRA_Neu', 50), checks)

  def test_no_window_adds_existing_soft_disable_and_low_speed_is_retained(self):
    class Events:
      def __init__(self): self.names = []
      def add(self, event): self.names.append(event)
      def to_msg(self): return self.names
    ret = NS(vEgo=52/3.6, cruiseState=NS(enabled=True, available=True))
    state = NS(update=lambda *args: ret, CP=NS(openpilotLongitudinalControl=False))
    interface = NS(CS=state, cp=None, cp_cam=None, cp_ext=None,
      CP=NS(transmissionType=0, minSteerSpeed=50/3.6), low_speed_alert=False,
      CC=NS(pq_hca_timer_reset=NS(takeover_required=True)),
      dp_atl_mode=lambda r: (True, True), create_common_events=lambda *a, **k: Events(),
      dp_atl_warning=lambda r, events: events)
    ns = {'GearShifter': NS(eco=1, sport=2, manumatic=3), 'ButtonType': NS(setCruise=1, resumeCruise=2),
      'EventName': NS(belowSteerSpeed='low', steerTempUnavailable='takeover')}
    update = method('interface.py', '_update', ns)
    self.assertEqual(update(interface, NS(enabled=True)).events, ['low', 'takeover'])


if __name__ == '__main__':
  unittest.main()
