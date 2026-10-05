import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "vendor/dragonpilot-beta2-c6-cruise/selfdrive/car/volkswagen/pq_stock_cruise.py"


def load_module():
  spec = importlib.util.spec_from_file_location("pq_stock_cruise_candidate", MODULE_PATH)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


class PqStockCruiseCandidateTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.module = load_module()

  def make_controller(self, mode=None):
    m = self.module
    selected_mode = m.StockCruiseMode.lead_trim if mode is None else mode
    return m.PqStockCruiseController(selected_mode, control_hz=10, lead_confirm_s=0.3,
                                     lead_lost_s=0.2, button_interval_s=0.1, ack_timeout_s=0.3)

  def slower_lead(self, v_rel_ms=-2.8):
    return self.module.LeadSample(True, 55.0, 0.1, v_rel_ms, 30.5, 0.95)

  def test_missing_mode_file_is_disabled(self):
    with tempfile.TemporaryDirectory() as tmp:
      self.assertEqual(self.module.read_mode(Path(tmp) / "missing"), self.module.StockCruiseMode.off)

  def test_observe_mode_calculates_but_never_commands(self):
    controller = self.make_controller(self.module.StockCruiseMode.observe)
    outputs = [controller.update(True, 120.0, 33.3, lead=self.slower_lead()) for _ in range(10)]
    self.assertTrue(all(output.command == self.module.ButtonCommand.none for output in outputs))
    self.assertEqual(outputs[-1].temporary_target_kph, 110.0)

  def test_automatic_mode_requests_one_press_and_waits_for_ack(self):
    controller = self.make_controller()
    outputs = [controller.update(True, 120.0, 33.3, lead=self.slower_lead()) for _ in range(3)]
    self.assertEqual(outputs[-1].command, self.module.ButtonCommand.decel)
    controller.mark_command_sent(120.0)
    self.assertTrue(controller.update(True, 120.0, 33.3, lead=self.slower_lead()).waiting_for_ack)

  def test_ack_timeout_latches_fault(self):
    controller = self.make_controller()
    for _ in range(3):
      controller.update(True, 120.0, 33.3, lead=self.slower_lead())
    controller.mark_command_sent(120.0)
    outputs = [controller.update(True, 120.0, 33.3, lead=self.slower_lead()) for _ in range(3)]
    self.assertTrue(outputs[-1].faulted)
    self.assertEqual(outputs[-1].command, self.module.ButtonCommand.none)


if __name__ == "__main__":
  unittest.main()
