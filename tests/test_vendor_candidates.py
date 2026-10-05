import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULES = {
  "release2": ROOT / "vendor/dragonpilot-release2/selfdrive/car/volkswagen/hca_timer_reset.py",
  "d2": ROOT / "vendor/dragonpilot-d2/selfdrive/car/volkswagen/hca_timer_reset.py",
  "beta2-c6": ROOT / "vendor/dragonpilot-beta2-c6/selfdrive/car/volkswagen/hca_timer_reset.py",
}


def load_module(name, path):
  spec = importlib.util.spec_from_file_location(name, path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


class VendorCandidateTest(unittest.TestCase):
  def test_candidates_are_disabled_by_default(self):
    for name, path in MODULES.items():
      module = load_module(name, path)
      self.assertFalse(module.PQ_LONG_STANDBY_ENABLED)

  def test_candidates_hold_100_zero_torque_frames(self):
    for name, path in MODULES.items():
      module = load_module(name, path)
      model = module.HcaTimerReset(message_hz=50, reset_after_s=1, standby_s=2)
      outputs = [model.update(True, 100) for _ in range(50 + 100)]
      disabled = [output for output in outputs if not output[1]]
      self.assertEqual(len(disabled), 100, name)
      self.assertTrue(all(output[0] == 0 for output in disabled), name)
      self.assertTrue(disabled[-1][2], name)


if __name__ == "__main__":
  unittest.main()
