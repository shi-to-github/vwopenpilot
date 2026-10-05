"""Build a reviewable, two-file HCA test package for the inspected a6eed9e C2."""

import hashlib
import json
import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]
TREE = ROOT / "vendor" / "dragonpilot-device-a6eed9e"
VW = TREE / "selfdrive" / "car" / "volkswagen"
BACKUP_VW = ROOT / "device-backups" / "original-20261001" / "working-files" / "volkswagen"
OUTPUT = ROOT / "candidate" / "device-a6eed9e-2s"
BASE_COMMIT = "a6eed9e0c4d9a242db1e35978d2c32fe427491c7"
REMOTE_RELATIVE = "selfdrive/car/volkswagen"


def sha256(data):
  return hashlib.sha256(data).hexdigest()


def write(path, data):
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(data)


def main():
  base_controller = subprocess.run(
    ["git", "-C", str(TREE), "show", f"{BASE_COMMIT}:{REMOTE_RELATIVE}/carcontroller.py"],
    check=True, capture_output=True,
  ).stdout
  captured_controller = (BACKUP_VW / "carcontroller.py").read_bytes()
  if captured_controller != base_controller:
    raise RuntimeError("Saved C2 controller does not match the pinned base commit")

  candidate_controller = (VW / "carcontroller.py").read_bytes()
  module = (VW / "hca_timer_reset.py").read_bytes()
  switch = b"PQ_LONG_STANDBY_ENABLED = False"
  if module.count(switch) != 1:
    raise RuntimeError("Cannot identify the single disabled HCA switch")
  enabled_module = module.replace(switch, b"PQ_LONG_STANDBY_ENABLED = True").rstrip(b"\r\n") + b"\n"

  deploy = OUTPUT / "deploy"
  rollback = OUTPUT / "rollback"
  write(deploy / "carcontroller.py", candidate_controller)
  write(deploy / "hca_timer_reset.py", enabled_module)
  write(rollback / "carcontroller.py", base_controller)

  manifest = {
    "base_commit": BASE_COMMIT,
    "device_branch": "beta2_sharan2",
    "remote_directory": f"/data/openpilot/{REMOTE_RELATIVE}",
    "hca_message_hz": 50,
    "reset_after_seconds": 240,
    "standby_seconds": 2,
    "remote_preconditions": {
      "carcontroller.py_sha256": sha256(base_controller),
      "hca_timer_reset.py": "absent",
    },
    "deploy_sha256": {
      "carcontroller.py": sha256(candidate_controller),
      "hca_timer_reset.py": sha256(enabled_module),
    },
    "rollback_sha256": {"carcontroller.py": sha256(base_controller)},
    "scope": "HCA only; interface.py and cruise buttons are not part of this package",
  }
  (OUTPUT / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
  print(f"Built {OUTPUT}")
  print(f"base_controller_sha256={sha256(base_controller)}")
  print(f"deploy_controller_sha256={sha256(candidate_controller)}")
  print(f"deploy_module_sha256={sha256(enabled_module)}")


if __name__ == "__main__":
  main()
