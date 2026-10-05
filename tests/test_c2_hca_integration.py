"""Exercise the installed C2 controller's CAN output with its exact 50 Hz HCA cadence."""

import ast
import importlib.util
import types
import unittest
from pathlib import Path


DEVICE_TREE = Path(__file__).resolve().parents[1] / "vendor" / "dragonpilot-device-a6eed9e"
VW = DEVICE_TREE / "selfdrive" / "car" / "volkswagen"


class Actuators:
  steer = 0.5

  def copy(self):
    return Actuators()


def load_controller(enable_reset):
  reset_file = VW / "hca_timer_reset.py"
  spec = importlib.util.spec_from_file_location("device_hca_timer_reset", reset_file)
  reset_module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(reset_module)

  controller_file = VW / "carcontroller.py"
  tree = ast.parse(controller_file.read_text(encoding="utf-8"))
  controller_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CarController")
  pq = types.SimpleNamespace(
    create_steering_control=lambda packer, bus, torque, enabled: ("HCA_1", torque, enabled),
    create_lka_hud_control=lambda *args: ("HUD",),
  )
  fingerprint = "VOLKSWAGEN PASSAT NMS"
  namespace = {
    "CANPacker": lambda name: object(),
    "CarControllerParams": lambda cp: types.SimpleNamespace(HCA_STEP=2, STEER_MAX=300,
                                                      ACC_CONTROL_STEP=100000, LDW_STEP=100000,
                                                      ACC_HUD_STEP=100000),
    "PQ_CARS": {fingerprint},
    "pqcan": pq,
    "mqbcan": pq,
    "HcaTimerReset": reset_module.HcaTimerReset,
    "PQ_LONG_STANDBY_ENABLED": enable_reset,
    "CANBUS": types.SimpleNamespace(pt=0),
    "VisualAlert": types.SimpleNamespace(steerRequired=1, ldw=2),
    "apply_std_steer_torque_limits": lambda new, last, driver, params: new,
  }
  exec(compile(ast.Module(body=[controller_class], type_ignores=[]), str(controller_file), "exec"), namespace)
  cp = types.SimpleNamespace(carFingerprint=fingerprint, pcmCruise=False,
                             openpilotLongitudinalControl=False)
  controller = namespace["CarController"]("unused", cp, None)
  cc = types.SimpleNamespace(
    actuators=Actuators(),
    hudControl=types.SimpleNamespace(visualAlert=0),
    cruiseControl=types.SimpleNamespace(cancel=False, resume=False),
    latActive=True,
    enabled=True,
  )
  cs = types.SimpleNamespace(
    out=types.SimpleNamespace(steeringTorque=0, steeringPressed=False),
    ldw_stock_values={}, gra_stock_values={"COUNTER": 0},
  )
  return controller, cc, cs


def hca_messages(seconds, enable_reset):
  controller, cc, cs = load_controller(enable_reset)
  messages = []
  for _ in range(seconds * 100):
    _, can_sends = controller.update(cc, cs, 0)
    messages.extend(message for message in can_sends if message[0] == "HCA_1")
  return messages


class C2HcaIntegrationTest(unittest.TestCase):
  def test_default_off_retains_original_one_frame_behavior(self):
    messages = hca_messages(120, False)
    standby = [i for i, (_, _, enabled) in enumerate(messages) if not enabled]
    self.assertEqual(standby, [5899])
    self.assertNotEqual(messages[5899][1], 0)

  def test_enabled_candidate_sends_100_zero_torque_standby_frames(self):
    messages = hca_messages(242, True)
    standby = [i for i, (_, torque, enabled) in enumerate(messages)
               if not enabled and torque == 0]
    self.assertEqual(standby, list(range(11999, 12099)))
    self.assertTrue(messages[12099][2])
    self.assertNotEqual(messages[12099][1], 0)


if __name__ == "__main__":
  unittest.main()
