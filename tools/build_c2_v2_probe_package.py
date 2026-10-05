"""Pin the local V1+stock-cruise-probe files to the inspected C2 baseline."""

import hashlib
import json
import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]
V1 = ROOT / "candidate" / "device-a6eed9e-2s"
V2 = ROOT / "candidate" / "device-a6eed9e-v2-probe"
BASE_COMMIT = "a6eed9e0c4d9a242db1e35978d2c32fe427491c7"
VW = "selfdrive/car/volkswagen"


def digest(data):
  return hashlib.sha256(data).hexdigest()


def main():
  v1_manifest = json.loads((V1 / "manifest.json").read_text(encoding="utf-8"))
  v1_controller = (V1 / "deploy" / "carcontroller.py").read_bytes()
  v1_hca = (V1 / "deploy" / "hca_timer_reset.py").read_bytes()
  base_pqcan = subprocess.run(
    ["git", "-C", str(ROOT / "vendor" / "dragonpilot-device-a6eed9e"),
     "show", f"{BASE_COMMIT}:{VW}/pqcan.py"],
    check=True, capture_output=True,
  ).stdout

  if digest(v1_controller) != v1_manifest["deploy_sha256"]["carcontroller.py"]:
    raise RuntimeError("Local V1 controller no longer matches its deployed manifest")
  if digest(v1_hca) != v1_manifest["deploy_sha256"]["hca_timer_reset.py"]:
    raise RuntimeError("Local V1 HCA module no longer matches its deployed manifest")
  if (V2 / "deploy" / "hca_timer_reset.py").read_bytes() != v1_hca:
    raise RuntimeError("V2 probe must preserve the exact V1 HCA module")
  if (V2 / "rollback" / "carcontroller.py").read_bytes() != v1_controller:
    raise RuntimeError("V2 rollback controller must be the deployed V1 controller")
  if (V2 / "rollback" / "pqcan.py").read_bytes() != base_pqcan:
    raise RuntimeError("V2 rollback pqcan must match the pinned device commit")

  names = ("carcontroller.py", "hca_timer_reset.py", "pqcan.py", "pq_stock_cruise_probe.py")
  deploy = {name: digest((V2 / "deploy" / name).read_bytes()) for name in names}
  for name in names:
    compile((V2 / "deploy" / name).read_bytes(), str(V2 / "deploy" / name), "exec")
  diagnostic_names = ("capture_cruise.py", "probe_control.py", "overlay_server.py")
  for name in diagnostic_names:
    compile((V2 / "diagnostics" / name).read_bytes(), str(V2 / "diagnostics" / name), "exec")

  manifest = {
    "base_commit": BASE_COMMIT,
    "device_branch": "beta2_sharan2",
    "package_type": "C2 field-test package; disabled by default",
    "default_mode": "V1; no stock-cruise button injection",
    "manual_probe_mode": "one explicit UP or DOWN short press per engagement; no automatic speed control",
    "preconditions_sha256": {
      "carcontroller.py": digest(v1_controller),
      "hca_timer_reset.py": digest(v1_hca),
      "pqcan.py": digest(base_pqcan),
      "pq_stock_cruise_probe.py": None,
    },
    "deploy_sha256": deploy,
    "rollback_sha256": {
      "carcontroller.py": digest(v1_controller),
      "pqcan.py": digest(base_pqcan),
      "pq_stock_cruise_probe.py": None,
    },
    "diagnostics_sha256": {name: digest((V2 / "diagnostics" / name).read_bytes())
                           for name in diagnostic_names},
    "startup_sha256": {
      "original_ui": digest((V2 / "rollback" / "ui").read_bytes()),
      "probe_ui": digest((V2 / "deploy" / "ui").read_bytes()),
      "boot_overlay.py": digest((V2 / "diagnostics" / "boot_overlay.py").read_bytes()),
    },
  }
  (V2 / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
  print(f"Built local V2 probe manifest: {V2 / 'manifest.json'}")


if __name__ == "__main__":
  main()
