"""Verify the raw PQ trace decoder and passenger's one-shot switch."""

import ast
import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
DIAG = ROOT / "candidate" / "device-a6eed9e-v2-probe" / "diagnostics"
DEPLOY = ROOT / "candidate" / "device-a6eed9e-v2-probe" / "deploy"


def load(path, name):
  spec = importlib.util.spec_from_file_location(name, path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


control = load(DIAG / "probe_control.py", "probe_control_test")
probe = load(DEPLOY / "pq_stock_cruise_probe.py", "cruise_probe_diag_test")
analyzer = load(ROOT / "tools" / "analyze_c2_cruise_trace.py", "cruise_analyzer_test")
tree = ast.parse((DIAG / "capture_cruise.py").read_text(encoding="utf-8"))
decode = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "decode_frame")
namespace = {"GRA_NEU": 906, "MOTOR_2": 648, "ACC_GRA_ANZEIGE": 1386}
exec(compile(ast.Module(body=[decode], type_ignores=[]), "capture_cruise.py", "exec"), namespace)


class V2DiagnosticsTest(unittest.TestCase):
  def test_raw_stalk_and_engine_setpoint_decode(self):
    gra = namespace["decode_frame"](906, bytes([0, 0b00001000, 0b01010000, 0]))
    self.assertTrue(gra["up_short"])
    self.assertFalse(gra["down_short"])
    self.assertEqual(gra["counter"], 5)
    motor = namespace["decode_frame"](648, bytes([0, 0, 0b01000000, 80, 100, 0, 0, 0]))
    self.assertEqual(motor["gra_status"], 1)
    self.assertEqual(motor["stock_set_kph"], 128.0)
    self.assertEqual(motor["motor_vehicle_kph"], 102.4)

  def test_passenger_switch_writes_expiring_command_and_marker(self):
    with tempfile.TemporaryDirectory() as directory:
      root = pathlib.Path(directory)
      with patch.object(control, "ROOT", root), patch.object(control, "MODE", root / "mode"), \
           patch.object(control, "COMMAND", root / "command"), patch.object(control, "EVENTS", root / "events"):
        for args in (("mode", "manual"), ("press", "up"), ("mark", "仪表加速")):
          with patch.object(sys, "argv", ["probe_control.py", *args]), contextlib.redirect_stdout(io.StringIO()):
            control.main()
        self.assertEqual(probe.consume_command(root / "command"), "up")
        self.assertFalse((root / "command").exists())
        self.assertEqual(len((root / "events").read_text(encoding="utf-8").splitlines()), 3)
        with patch.object(sys, "argv", ["probe_control.py", "mode", "v1"]), \
             contextlib.redirect_stdout(io.StringIO()):
          control.main()
        self.assertEqual((root / "mode").read_text(encoding="utf-8").strip(), "0")

  def test_trace_summary_keeps_button_edges_and_speed_changes(self):
    with tempfile.TemporaryDirectory() as directory:
      trace = pathlib.Path(directory) / "trace.jsonl"
      records = [
        {"type": "can", "t_mono_ns": 1000, "name": "GRA_Neu", "src": 0, "up_short": True},
        {"type": "can", "t_mono_ns": 2000, "name": "GRA_Neu", "src": 0, "up_short": True},
        {"type": "can", "t_mono_ns": 3000, "name": "Motor_2", "stock_set_kph": 110.08,
         "gra_status": 1},
        {"type": "operator", "kind": "manual_observation", "note": "仪表加速"},
      ]
      trace.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
      lines, counts = analyzer.summarize(trace)
      self.assertEqual(sum("GRA up_short" in line for line in lines), 1)
      self.assertTrue(any("110.08" in line for line in lines))
      self.assertEqual(counts["GRA_Neu"], 2)


if __name__ == "__main__":
  unittest.main()
