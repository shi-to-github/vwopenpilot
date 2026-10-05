"""Run V2's actual remote apply code against an isolated V1 checkout."""

import contextlib
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import manage_c2_v2_probe_package as manager  # noqa: E402


class V2ProbeManagerTest(unittest.TestCase):
  def setUp(self):
    temporary = tempfile.TemporaryDirectory()
    self.addCleanup(temporary.cleanup)
    self.root = pathlib.Path(temporary.name)
    self.base = self.root / "openpilot"
    self.vw = self.base / "selfdrive" / "car" / "volkswagen"
    self.vw.mkdir(parents=True)
    self.stage = self.root / "stage"
    self.stage.mkdir()
    self.params = self.root / "params"
    self.params.mkdir()
    self.mode = self.root / "stock_cruise_probe_mode"
    self.command = self.root / "stock_cruise_probe_command"
    self.capture = self.root / "capture_cruise.py"
    self.control = self.root / "probe_control.py"
    self.overlay = self.root / "overlay_server.py"
    self.boot = self.root / "boot_overlay.py"
    self.ui = self.base / "selfdrive" / "ui" / "ui"
    self.ui.parent.mkdir(parents=True)
    self.hold = self.root / "update-hold.json"
    self.hold.write_text("{}", encoding="utf-8")
    for name, value in (("IsOffroad", "1"), ("DisableUpdates", "1"),
                        ("UpdateAvailable", "0"), ("UpdaterState", "idle")):
      (self.params / name).write_text(value, encoding="utf-8")

    package = manager.PACKAGE
    shutil.copyfile(package / "rollback" / "ui", self.ui)
    shutil.copyfile(package / "rollback" / "ui", self.stage / "boot-old-ui")
    for name in ("carcontroller.py", "pqcan.py"):
      shutil.copyfile(package / "rollback" / name, self.vw / name)
      shutil.copyfile(package / "rollback" / name, self.stage / ("old-" + name))
    shutil.copyfile(package / "deploy" / "hca_timer_reset.py", self.vw / "hca_timer_reset.py")
    for name in ("carcontroller.py", "pqcan.py", "hca_timer_reset.py", "pq_stock_cruise_probe.py"):
      shutil.copyfile(package / "deploy" / name, self.stage / ("new-" + name))
    for name in ("capture_cruise.py", "probe_control.py", "overlay_server.py"):
      shutil.copyfile(package / "diagnostics" / name, self.stage / ("new-" + name))

    subprocess.run(["git", "init", "-q", str(self.base)], check=True)
    subprocess.run(["git", "-C", str(self.base), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(self.base), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(self.base), "config", "core.autocrlf", "false"], check=True)
    subprocess.run(["git", "-C", str(self.base), "checkout", "-qb", "beta2_sharan2"], check=True)
    subprocess.run(["git", "-C", str(self.base), "add", "."], check=True)
    subprocess.run(["git", "-C", str(self.base), "commit", "-qm", "fixture"], check=True)
    self.manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    self.manifest["base_commit"] = subprocess.check_output(
      ["git", "-C", str(self.base), "rev-parse", "HEAD"], text=True).strip()

  def run_remote(self, action):
    code = manager.REMOTE
    for old, new in (("/data/openpilot", self.base),
                     ("/data/pq46_v2_probe_staging", self.stage),
                     ("/data/params/d_tmp", self.params),
                     ("/data/pq46/stock_cruise_probe_mode", self.mode),
                     ("/data/pq46/stock_cruise_probe_command", self.command),
                     ("/data/pq46/capture_cruise.py", self.capture),
                     ("/data/pq46/probe_control.py", self.control),
                     ("/data/pq46/overlay_server.py", self.overlay),
                     ("/data/pq46/boot_overlay.py", self.boot),
                     ("/data/pq46_hca_staging/update-hold.json", self.hold)):
      code = code.replace(f"pathlib.Path('{old}')", f"pathlib.Path({str(new)!r})")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
      exec(compile(code, "v2_remote.py", "exec"),
           {"CONFIG": self.manifest, "ACTION": action, "PARKED_IGNITION": False})
    return json.loads(output.getvalue())

  def test_install_and_rollback_preserve_v1_hca(self):
    self.assertEqual(self.run_remote("status")["package_state"], "READY_FROM_V1")
    self.assertEqual(self.run_remote("install")["mode"], "V1 default")
    self.assertEqual(self.run_remote("status")["package_state"], "PROBE_PRESENT")
    self.assertTrue(self.capture.is_file())
    self.assertTrue(self.control.is_file())
    self.assertTrue(self.overlay.is_file())
    self.assertFalse(self.mode.exists())
    shutil.copyfile(manager.PACKAGE / "deploy" / "ui", self.ui)
    shutil.copyfile(manager.PACKAGE / "diagnostics" / "boot_overlay.py", self.boot)
    self.assertEqual(self.run_remote("rollback")["action"], "rolled_back_to_v1")
    self.assertEqual(self.run_remote("status")["package_state"], "READY_FROM_V1")
    self.assertFalse(self.capture.exists())
    self.assertFalse(self.control.exists())
    self.assertFalse(self.overlay.exists())
    self.assertFalse(self.boot.exists())
    self.assertEqual(self.ui.read_bytes(), (manager.PACKAGE / "rollback" / "ui").read_bytes())
    self.assertEqual((self.vw / "hca_timer_reset.py").read_bytes(),
                     (manager.PACKAGE / "deploy" / "hca_timer_reset.py").read_bytes())

  def test_refuses_without_update_hold_or_offroad(self):
    self.hold.unlink()
    with self.assertRaisesRegex(RuntimeError, "update hold"):
      self.run_remote("install")
    self.hold.write_text("{}", encoding="utf-8")
    (self.params / "IsOffroad").write_text("0", encoding="utf-8")
    with self.assertRaisesRegex(RuntimeError, "offroad"):
      self.run_remote("install")

  def test_refuses_unexpected_files_or_armed_mode(self):
    self.mode.write_text("2", encoding="utf-8")
    with self.assertRaisesRegex(RuntimeError, "mode or command"):
      self.run_remote("install")
    self.mode.unlink()
    (self.vw / "pqcan.py").write_text("unknown local change", encoding="utf-8")
    with self.assertRaisesRegex(RuntimeError, "differ"):
      self.run_remote("install")


if __name__ == "__main__":
  unittest.main()
