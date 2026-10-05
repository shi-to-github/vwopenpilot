import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "candidate"))
from hca_reset_model import HcaTimerResetModel


class HcaTimerResetModelTest(unittest.TestCase):
  def test_two_seconds_is_100_standby_frames_at_50_hz(self):
    model = HcaTimerResetModel(control_hz=50, reset_after_s=4, standby_s=2)
    outputs = [model.update(True, 100) for _ in range(200 + 100)]
    forced = [output for output in outputs if output.forced_standby]
    self.assertEqual(len(forced), 100)
    self.assertTrue(all(not output.enabled and output.torque == 0 for output in forced))
    self.assertTrue(forced[-1].reset_completed)

  def test_two_seconds_scales_with_message_rate(self):
    for hz, expected in ((20, 40), (50, 100), (100, 200)):
      model = HcaTimerResetModel(control_hz=hz, reset_after_s=1, standby_s=2)
      outputs = [model.update(True, 50) for _ in range(hz + expected)]
      self.assertEqual(sum(output.forced_standby for output in outputs), expected)

  def test_short_natural_standby_does_not_clear_accumulated_time(self):
    model = HcaTimerResetModel(control_hz=50, reset_after_s=10, standby_s=2)
    for _ in range(5 * 50):
      model.update(True, 80)
    for _ in range(25):
      model.update(True, 0)
    output = model.update(True, 80)
    self.assertAlmostEqual(output.active_elapsed_s, 5.02, places=6)

  def test_long_natural_standby_clears_accumulated_time(self):
    model = HcaTimerResetModel(control_hz=50, reset_after_s=10, standby_s=2)
    for _ in range(5 * 50):
      model.update(True, 80)
    outputs = [model.update(True, 0) for _ in range(2 * 50)]
    self.assertTrue(outputs[-1].reset_completed)
    output = model.update(True, 80)
    self.assertAlmostEqual(output.active_elapsed_s, 0.02, places=6)

  def test_disengagement_clears_model_state(self):
    model = HcaTimerResetModel(control_hz=50, reset_after_s=10, standby_s=2)
    for _ in range(4 * 50):
      model.update(True, 40)
    output = model.update(False, 0)
    self.assertFalse(output.enabled)
    self.assertEqual(output.active_elapsed_s, 0)
    output = model.update(True, 40)
    self.assertAlmostEqual(output.active_elapsed_s, 0.02, places=6)


if __name__ == "__main__":
  unittest.main()

