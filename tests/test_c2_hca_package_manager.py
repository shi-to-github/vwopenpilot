"""Run the same install/rollback code used over SSH against a temporary checkout."""

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
import manage_c2_hca_package as manager  # noqa: E402


class C2PackageManagerTest(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = pathlib.Path(self.temp.name)
    self.base = self.root / "openpilot"
    self.vw = self.base / "selfdrive" / "car" / "volkswagen"
    self.vw.mkdir(parents=True)
    self.stage = self.root / "stage"
    self.stage.mkdir()
    self.params = self.root / "params"
    self.params.mkdir()
    for name, value in (("IsOffroad", "1"), ("UpdateAvailable", "0"),
                        ("UpdaterState", "idle")):
      (self.params / name).write_text(value, encoding="utf-8")

    package = ROOT / "candidate" / "device-a6eed9e-2s"
    shutil.copyfile(package / "rollback" / "carcontroller.py", self.vw / "carcontroller.py")
    shutil.copyfile(package / "rollback" / "carcontroller.py", self.stage / "carcontroller-original.py")
    shutil.copyfile(package / "deploy" / "carcontroller.py", self.stage / "carcontroller-new.py")
    shutil.copyfile(package / "deploy" / "hca_timer_reset.py", self.stage / "hca_timer_reset-new.py")

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

  def run_remote_action(self, action):
    code = manager.REMOTE_ACTION
    for old, new in (("/data/openpilot", self.base),
                     ("/data/pq46_hca_staging", self.stage),
                     ("/data/params/d_tmp", self.params)):
      code = code.replace(f"pathlib.Path('{old}')", f"pathlib.Path({str(new)!r})")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
      exec(compile(code, "remote_action.py", "exec"),
           {"CONFIG": self.manifest, "ACTION": action, "PARKED_IGNITION": False})
    return output.getvalue()

  def test_install_then_rollback_restores_exact_files(self):
    self.assertIn("installed", self.run_remote_action("install"))
    self.assertEqual((self.vw / "carcontroller.py").read_bytes(),
                     (manager.PACKAGE / "deploy" / "carcontroller.py").read_bytes())
    self.assertEqual((self.vw / "hca_timer_reset.py").read_bytes(),
                     (manager.PACKAGE / "deploy" / "hca_timer_reset.py").read_bytes())
    self.assertIn("rolled_back", self.run_remote_action("rollback"))
    self.assertEqual((self.vw / "carcontroller.py").read_bytes(),
                     (manager.PACKAGE / "rollback" / "carcontroller.py").read_bytes())
    self.assertFalse((self.vw / "hca_timer_reset.py").exists())

  def test_refuses_install_without_offroad_state(self):
    (self.params / "IsOffroad").write_text("0", encoding="utf-8")
    with self.assertRaisesRegex(RuntimeError, "offroad"):
      self.run_remote_action("install")
    self.assertFalse((self.vw / "hca_timer_reset.py").exists())

  def test_refuses_install_while_updater_is_active(self):
    (self.params / "UpdaterState").write_text("checking...", encoding="utf-8")
    with self.assertRaisesRegex(RuntimeError, "Updater"):
      self.run_remote_action("install")
    self.assertFalse((self.vw / "hca_timer_reset.py").exists())


if __name__ == "__main__":
  unittest.main()
