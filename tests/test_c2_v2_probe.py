"""Check the disabled-by-default PQ stock cruise probe without a car or Panda."""

import importlib.util
import json
import pathlib
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBE = ROOT / "candidate" / "device-a6eed9e-v2-probe" / "deploy" / "pq_stock_cruise_probe.py"
PQC = ROOT / "candidate" / "device-a6eed9e-v2-probe" / "deploy" / "pqcan.py"


def load(path, name):
  spec = importlib.util.spec_from_file_location(name, path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


probe = load(PROBE, "pq_stock_cruise_probe_test")
pqcan = load(PQC, "pqcan_probe_test")


class FakePacker:
  def make_can_msg(self, name, bus, values):
    return name, bus, values


class C2V2ProbeTest(unittest.TestCase):
  def test_missing_or_invalid_mode_defaults_to_v1(self):
    self.assertEqual(probe.read_mode("/nonexistent-pq46-mode"), probe.ProbeMode.v1)
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
      invalid = pathlib.Path(directory) / "mode"
      invalid.write_text("3", encoding="utf-8")
      self.assertEqual(probe.read_mode(invalid), probe.ProbeMode.v1)

  def test_auto_mode_requires_live_server_heartbeat(self):
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
      mode = pathlib.Path(directory) / "mode"
      heartbeat = pathlib.Path(directory) / "heartbeat"
      mode.write_text("3", encoding="utf-8")
      with patch.object(probe, "HEARTBEAT_PATH", str(heartbeat)):
        self.assertEqual(probe.read_mode(mode), probe.ProbeMode.v1)
        heartbeat.touch()
        self.assertEqual(probe.read_mode(mode), probe.ProbeMode.auto_once)

  def test_v1_and_observe_never_request_button(self):
    for mode in (probe.ProbeMode.v1, probe.ProbeMode.observe):
      controller = probe.StockCruiseProbe(mode)
      self.assertFalse(controller.update(True, 120, 110, command="down"))

  def test_manual_press_requires_all_gates(self):
    inputs = (
      {"active": False}, {"set_speed_kph": -1}, {"v_ego_kph": 54},
      {"brake_pressed": True}, {"gas_pressed": True},
      {"driver_button_active": True},
    )
    for replacement in inputs:
      values = {"active": True, "set_speed_kph": 120, "v_ego_kph": 100,
                "command": "down"}
      values.update(replacement)
      self.assertFalse(probe.StockCruiseProbe(probe.ProbeMode.manual_once).update(**values))

  def test_only_one_command_per_engagement_and_acknowledgement(self):
    controller = probe.StockCruiseProbe(probe.ProbeMode.manual_once)
    self.assertTrue(controller.update(True, 120, 100, command="down"))
    self.assertTrue(controller.mark_sent(120))
    self.assertFalse(controller.update(True, 120, 100))
    self.assertFalse(controller.update(True, 110, 100))
    self.assertFalse(controller.waiting)
    self.assertFalse(controller.update(True, 110, 100, command="down"))
    controller.update(False, 0, 0)
    self.assertTrue(controller.update(True, 120, 100, command="down"))

  def test_missing_ack_or_counter_fails_closed(self):
    controller = probe.StockCruiseProbe(probe.ProbeMode.manual_once, hz=10)
    controller.update(True, 120, 100, command="down")
    for _ in range(10):
      controller.update(True, 120, 100)
    self.assertTrue(controller.faulted)
    self.assertFalse(controller.pending)

    controller = probe.StockCruiseProbe(probe.ProbeMode.manual_once, hz=10)
    controller.update(True, 120, 100, command="down")
    controller.mark_sent(120)
    for _ in range(15):
      controller.update(True, 120, 100)
    self.assertTrue(controller.faulted)
    self.assertFalse(controller.update(True, 120, 100, command="down"))

  def test_up_and_unknown_setpoint_require_manual_observation(self):
    controller = probe.StockCruiseProbe(probe.ProbeMode.manual_once, hz=10)
    self.assertTrue(controller.update(True, 0, 100, command="up"))
    self.assertEqual(controller.direction, "up")
    controller.mark_sent(0)
    for _ in range(15):
      controller.update(True, 0, 100)
    self.assertTrue(controller.faulted)
    self.assertIn("Motor_2", controller.reason)

  def test_auto_mode_waits_for_stable_engagement_then_only_one_down(self):
    controller = probe.StockCruiseProbe(probe.ProbeMode.auto_once, hz=10)
    for _ in range(49):
      self.assertFalse(controller.update(True, 0, 80))
    self.assertTrue(controller.update(True, 0, 80))
    self.assertEqual(controller.direction, "down")
    controller.mark_sent(0)
    controller.update(False, 0, 0)
    for _ in range(60):
      self.assertFalse(controller.update(True, 0, 80))

  def test_auto_mode_resets_stability_on_driver_input(self):
    controller = probe.StockCruiseProbe(probe.ProbeMode.auto_once, hz=10)
    for _ in range(40):
      controller.update(True, 0, 80)
    self.assertFalse(controller.update(True, 0, 80, brake_pressed=True))
    for _ in range(49):
      self.assertFalse(controller.update(True, 0, 80))
    self.assertTrue(controller.update(True, 0, 80))

  def test_auto_mode_does_not_arm_near_lateral_minimum(self):
    controller = probe.StockCruiseProbe(probe.ProbeMode.auto_once, hz=10)
    for _ in range(100):
      self.assertFalse(controller.update(True, 0, 65))

  def test_command_is_one_shot_and_expires(self):
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
      path = pathlib.Path(directory) / "command"
      path.write_text(json.dumps({"direction": "up", "created_unix_ns": 1000}))
      self.assertEqual(probe.consume_command(path, now_ns=2000), "up")
      self.assertFalse(path.exists())
      path.write_text(json.dumps({"direction": "down", "created_unix_ns": 1000}))
      self.assertEqual(probe.consume_command(path, now_ns=6_000_000_001), "")
      self.assertFalse(path.exists())

  def test_pqcan_sets_only_one_decel_button(self):
    original = {"COUNTER": 4, "GRA_Up_kurz": 0, "GRA_Down_kurz": 0,
                "GRA_Abbrechen": 0, "GRA_Recall": 0}
    name, bus, values = pqcan.create_acc_buttons_control(FakePacker(), 1, original, 5, decel=True)
    self.assertEqual((name, bus, values["COUNTER"]), ("GRA_Neu", 1, 5))
    self.assertEqual(values["GRA_Down_kurz"], True)
    self.assertEqual(values["GRA_Up_kurz"], 0)
    self.assertEqual(values["GRA_Abbrechen"], False)
    self.assertEqual(values["GRA_Recall"], False)
    self.assertEqual(original["COUNTER"], 4)

  def test_pqcan_up_is_exclusive(self):
    original = {"COUNTER": 4, "GRA_Up_kurz": 0, "GRA_Down_kurz": 0}
    _, _, values = pqcan.create_acc_buttons_control(FakePacker(), 1, original, 5, accel=True)
    self.assertTrue(values["GRA_Up_kurz"])
    self.assertFalse(values["GRA_Down_kurz"])
    with self.assertRaises(ValueError):
      pqcan.create_acc_buttons_control(FakePacker(), 1, original, 5, accel=True, decel=True)

  def test_cancel_passthrough_matches_original_button_copy(self):
    original = {"COUNTER": 4, "GRA_Up_kurz": 1, "GRA_Down_kurz": 0}
    _, _, values = pqcan.create_acc_buttons_control(FakePacker(), 1, original, 5, cancel=True)
    self.assertEqual(values["GRA_Up_kurz"], 1)
    self.assertEqual(values["GRA_Down_kurz"], 0)


if __name__ == "__main__":
  unittest.main()
