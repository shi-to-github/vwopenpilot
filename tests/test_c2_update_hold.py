"""Exercise the temporary updater hold and restoration against fake parameters."""

import contextlib
import io
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import hold_c2_updates as hold  # noqa: E402


class FakeParams:
  values = {}

  def get_bool(self, key):
    return self.values.get(key) == "1"

  def get(self, key, encoding=None):
    return self.values.get(key)

  def put_bool(self, key, value):
    self.values[key] = "1" if value else "0"

  def put(self, key, value):
    self.values[key] = value


class C2UpdateHoldTest(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.stage = pathlib.Path(self.temp.name) / "stage"
    self.module = pathlib.Path(self.temp.name) / "hca_timer_reset.py"
    FakeParams.values = {
      "IsOffroad": "1", "UpdateAvailable": "0",
      "UpdaterState": "checking...", "DisableUpdates": "0",
    }

  def run_action(self, action):
    code = hold.REMOTE.replace(
      "pathlib.Path('/data/pq46_hca_staging')", f"pathlib.Path({str(self.stage)!r})"
    ).replace(
      "pathlib.Path('/data/openpilot/selfdrive/car/volkswagen/hca_timer_reset.py')",
      f"pathlib.Path({str(self.module)!r})"
    ).replace("time.sleep(1)", "time.sleep(0)")
    params_module = types.ModuleType("common.params")
    params_module.Params = FakeParams
    psutil_module = types.ModuleType("psutil")
    psutil_module.process_iter = lambda *args: []
    psutil_module.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
    psutil_module.AccessDenied = type("AccessDenied", (Exception,), {})
    output = io.StringIO()
    with patch.dict(sys.modules, {"common.params": params_module, "psutil": psutil_module}):
      with contextlib.redirect_stdout(output):
        exec(compile(code, "hold_remote.py", "exec"), {"ACTION": action})
    return output.getvalue()

  def test_pause_and_resume_restore_previous_setting(self):
    self.run_action("pause")
    self.assertEqual(FakeParams.values["DisableUpdates"], "1")
    self.assertEqual(FakeParams.values["UpdaterState"], "idle")
    self.assertTrue((self.stage / "update-hold.json").is_file())
    self.run_action("resume")
    self.assertEqual(FakeParams.values["DisableUpdates"], "0")
    self.assertFalse((self.stage / "update-hold.json").exists())

  def test_refuses_interrupting_file_update(self):
    FakeParams.values["UpdaterState"] = "finalizing update..."
    with self.assertRaisesRegex(RuntimeError, "changing files"):
      self.run_action("pause")
    self.assertEqual(FakeParams.values["DisableUpdates"], "0")

  def test_resume_requires_candidate_rollback_first(self):
    self.run_action("pause")
    self.module.write_text("candidate", encoding="utf-8")
    with self.assertRaisesRegex(RuntimeError, "roll back first"):
      self.run_action("resume")
    self.assertEqual(FakeParams.values["DisableUpdates"], "1")


if __name__ == "__main__":
  unittest.main()
