"""Exercise the exact V2 controller class with fake CAN and stock cruise feedback."""

import ast
import importlib.util
import pathlib
import types
import unittest


DEPLOY = pathlib.Path(__file__).resolve().parents[1] / "candidate" / "device-a6eed9e-v2-probe" / "deploy"


def load_module(name, path):
  spec = importlib.util.spec_from_file_location(name, path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


probe = load_module("controller_probe_module", DEPLOY / "pq_stock_cruise_probe.py")
hca = load_module("controller_hca_module", DEPLOY / "hca_timer_reset.py")
pqcan = load_module("controller_pqcan_module", DEPLOY / "pqcan.py")


class Packer:
  def make_can_msg(self, name, bus, values):
    return name, bus, values


class Actuators:
  steer = 0.5

  def copy(self):
    return Actuators()


def controller_for(mode, manual_command="", set_speed_kph=120, stock_enabled=True):
  source = DEPLOY / "carcontroller.py"
  tree = ast.parse(source.read_text(encoding="utf-8"))
  controller_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CarController")
  namespace = {
    "CANPacker": lambda dbc: Packer(),
    "CarControllerParams": lambda cp: types.SimpleNamespace(
      HCA_STEP=2, STEER_MAX=300, ACC_CONTROL_STEP=100000,
      LDW_STEP=100000, ACC_HUD_STEP=100000),
    "PQ_CARS": {"VOLKSWAGEN SHARAN 2ND GEN"},
    "pqcan": pqcan, "mqbcan": pqcan,
    "HcaTimerReset": hca.HcaTimerReset, "PQ_LONG_STANDBY_ENABLED": True,
    "ProbeMode": probe.ProbeMode, "StockCruiseProbe": probe.StockCruiseProbe,
    "read_mode": lambda: mode, "consume_command": lambda: manual_command,
    "CANBUS": types.SimpleNamespace(pt=0),
    "VisualAlert": types.SimpleNamespace(steerRequired=1, ldw=2),
    "apply_std_steer_torque_limits": lambda new, last, driver, params: new,
    "CV": types.SimpleNamespace(MS_TO_KPH=3.6),
  }
  exec(compile(ast.Module(body=[controller_class], type_ignores=[]), str(source), "exec"), namespace)
  cp = types.SimpleNamespace(carFingerprint="VOLKSWAGEN SHARAN 2ND GEN",
                             pcmCruise=True, openpilotLongitudinalControl=False)
  controller = namespace["CarController"]("unused", cp, None)
  cc = types.SimpleNamespace(
    actuators=Actuators(),
    hudControl=types.SimpleNamespace(visualAlert=0, leftLaneDepart=False,
                                     leftLaneVisible=True, rightLaneDepart=False,
                                     rightLaneVisible=True),
    cruiseControl=types.SimpleNamespace(cancel=False, resume=False),
    latActive=True, enabled=True,
  )
  cs = types.SimpleNamespace(
    out=types.SimpleNamespace(
      steeringTorque=0, steeringPressed=False,
      cruiseState=types.SimpleNamespace(enabled=stock_enabled, speed=set_speed_kph / 3.6),
      vEgo=100 / 3.6, brakePressed=False, gasPressed=False),
    ldw_stock_values={},
    gra_stock_values={"COUNTER": 0, "GRA_Abbrechen": 0, "GRA_Neu_Setzen": 0,
                      "GRA_Up_lang": 0, "GRA_Down_lang": 0, "GRA_Up_kurz": 0,
                      "GRA_Down_kurz": 0, "GRA_Recall": 0, "GRA_Zeitluecke": 0},
  )
  return controller, cc, cs


class V2ControllerIntegrationTest(unittest.TestCase):
  def test_default_v1_sends_hca_but_no_cruise_press(self):
    controller, cc, cs = controller_for(probe.ProbeMode.v1, "down")
    _, sent = controller.update(cc, cs, 0)
    self.assertNotIn("GRA_Neu", [message[0] for message in sent])
    self.assertIn("HCA_1", [message[0] for message in sent])
    self.assertTrue(sent[0][2]["LM_Offset"])

  def test_observe_sends_nothing_extra(self):
    controller, cc, cs = controller_for(probe.ProbeMode.observe, "down")
    _, sent = controller.update(cc, cs, 0)
    self.assertNotIn("GRA_Neu", [message[0] for message in sent])

  def test_explicit_manual_down_sends_only_one_frame(self):
    controller, cc, cs = controller_for(probe.ProbeMode.manual_once, "down")
    _, sent = controller.update(cc, cs, 0)
    gra = [message for message in sent if message[0] == "GRA_Neu"]
    self.assertEqual(len(gra), 1)
    self.assertEqual(gra[0][2]["GRA_Down_kurz"], True)
    self.assertEqual(gra[0][2]["GRA_Abbrechen"], False)
    self.assertEqual(gra[0][2]["GRA_Recall"], False)
    _, sent = controller.update(cc, cs, 0)
    self.assertNotIn("GRA_Neu", [message[0] for message in sent])

  def test_up_can_be_probed_when_c2_setpoint_is_unavailable(self):
    controller, cc, cs = controller_for(probe.ProbeMode.manual_once, "up", 0)
    _, sent = controller.update(cc, cs, 0)
    gra = [message for message in sent if message[0] == "GRA_Neu"]
    self.assertEqual(len(gra), 1)
    self.assertTrue(gra[0][2]["GRA_Up_kurz"])
    self.assertFalse(gra[0][2]["GRA_Down_kurz"])

  def test_mode_toggle_cannot_repeat_press_in_same_engagement(self):
    controller, cc, cs = controller_for(probe.ProbeMode.manual_once, "down")
    controller.update(cc, cs, 0)
    mode = [probe.ProbeMode.v1]
    controller.update.__globals__["read_mode"] = lambda: mode[0]
    controller.frame = 100
    cs.gra_stock_values["COUNTER"] = 1
    controller.update(cc, cs, 0)
    mode[0] = probe.ProbeMode.manual_once
    controller.frame = 200
    cs.gra_stock_values["COUNTER"] = 2
    _, sent = controller.update(cc, cs, 0)
    self.assertNotIn("GRA_Neu", [message[0] for message in sent])

  def test_v1_hca_keeps_the_100_frame_standby(self):
    controller, cc, cs = controller_for(probe.ProbeMode.v1)
    standby = []
    for frame in range(24200):
      _, sent = controller.update(cc, cs, 0)
      for name, _, values in sent:
        if name == "HCA_1" and values["HCA_Status"] == 3 and values["LM_Offset"] == 0:
          standby.append(frame // 2)
    self.assertEqual(standby, list(range(11999, 12099)))


if __name__ == "__main__":
  unittest.main()
