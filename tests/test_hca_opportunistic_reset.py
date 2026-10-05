import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "vendor/dragonpilot-beta2-c6-opportunistic/selfdrive/car/volkswagen/hca_opportunistic_reset.py"
SPEC = importlib.util.spec_from_file_location("hca_opportunistic_reset", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
HcaOpportunisticReset = MODULE.HcaOpportunisticReset


class HcaOpportunisticResetTest(unittest.TestCase):
  def make_reset(self):
    return HcaOpportunisticReset(message_hz=50, steer_max=300, search_after_s=4,
                                 alert_after_s=7,
                                 low_torque_fraction=0.20, low_torque_hold_s=0.5,
                                 standby_s=2.0)

  def test_disabled_by_default(self):
    self.assertFalse(MODULE.PQ_OPPORTUNISTIC_RESET_ENABLED)

  def test_high_torque_never_forces_timed_cut(self):
    reset = self.make_reset()
    outputs = [reset.update(True, 100) for _ in range(20 * 50)]
    self.assertTrue(all(enabled and torque == 100 for torque, enabled, _, _ in outputs))
    self.assertTrue(reset.approaching_timeout)

  def test_low_torque_window_starts_exact_two_second_standby(self):
    reset = self.make_reset()
    for _ in range(4 * 50):
      reset.update(True, 100)

    qualification = [reset.update(True, 30) for _ in range(25)]
    self.assertTrue(all(enabled for _, enabled, _, _ in qualification[:-1]))
    self.assertFalse(qualification[-1][1])

    standby = [qualification[-1]] + [reset.update(True, 30) for _ in range(99)]
    self.assertEqual(sum(not enabled for _, enabled, _, _ in standby), 100)
    self.assertTrue(standby[-1][2])

  def test_rising_demand_aborts_standby(self):
    reset = self.make_reset()
    for _ in range(4 * 50):
      reset.update(True, 100)
    for _ in range(25):
      reset.update(True, 30)
    for _ in range(20):
      reset.update(True, 30)

    torque, enabled, completed, aborted = reset.update(True, 6, demand_torque=100)
    self.assertEqual(torque, 6)
    self.assertTrue(enabled)
    self.assertFalse(completed)
    self.assertTrue(aborted)

  def test_natural_two_second_standby_resets_before_search_window(self):
    reset = self.make_reset()
    for _ in range(2 * 50):
      reset.update(True, 100)
    outputs = [reset.update(True, 0) for _ in range(2 * 50)]
    self.assertTrue(outputs[-1][2])
    self.assertEqual(reset.active_frames, 0)

  def test_disengagement_clears_state(self):
    reset = self.make_reset()
    for _ in range(3 * 50):
      reset.update(True, 100)
    reset.update(False, 0)
    self.assertEqual(reset.active_frames, 0)
    self.assertEqual(reset.low_torque_frames, 0)
    self.assertFalse(reset.forcing_standby)


if __name__ == "__main__":
  unittest.main()
