"""Read-only check that the staged HCA package matches the connected C2."""

import argparse
import json
import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "candidate" / "device-a6eed9e-2s" / "manifest.json"
PARKED_GUARD = ROOT / "tools" / "c2_parked_guard.py"

REMOTE_CHECK = """
import hashlib, json, pathlib, subprocess

base = pathlib.Path('/data/openpilot')
vw = base / 'selfdrive' / 'car' / 'volkswagen'
params = pathlib.Path('/data/params/d_tmp')

def digest(path):
  return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def param(name):
  path = params / name
  return path.read_text(errors='replace').strip() if path.is_file() else None

def git(*arguments):
  return subprocess.check_output(['git', '-C', str(base), *arguments], text=True).strip()

print(json.dumps({
  'branch': git('rev-parse', '--abbrev-ref', 'HEAD'),
  'commit': git('rev-parse', 'HEAD'),
  'carcontroller_sha256': digest(vw / 'carcontroller.py'),
  'hca_timer_reset_sha256': digest(vw / 'hca_timer_reset.py'),
  'interface_sha256': digest(vw / 'interface.py'),
  'IsOffroad': param('IsOffroad'),
  'UpdateAvailable': param('UpdateAvailable'),
  'UpdaterState': param('UpdaterState'),
  'DisableUpdates': param('DisableUpdates'),
  'update_hold_marker': pathlib.Path('/data/pq46_hca_staging/update-hold.json').is_file(),
}))
"""


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--ip", required=True)
  parser.add_argument("--port", type=int, default=8022)
  parser.add_argument("--user", default="root")
  parser.add_argument("--identity", type=pathlib.Path,
                      default=pathlib.Path.home() / ".ssh" / "vwopenploot_c2_id_rsa")
  parser.add_argument("--known-hosts", type=pathlib.Path,
                      default=pathlib.Path.home() / ".ssh" / "known_hosts_vwopenploot_c2")
  parser.add_argument("--parked-ignition", action="store_true",
                      help="Permit ignition on only after repeated live Park/standstill/disengaged checks")
  args = parser.parse_args()

  manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
  command = [
    "ssh", "-p", str(args.port), "-i", str(args.identity),
    "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=yes",
    "-o", f"UserKnownHostsFile={args.known_hosts}",
    f"{args.user}@{args.ip}", "python3 -",
  ]
  response = subprocess.run(command, input=REMOTE_CHECK, text=True,
                            capture_output=True, check=True)
  state = json.loads(response.stdout)
  expected = manifest["remote_preconditions"]
  deployed = manifest["deploy_sha256"]
  if (state["carcontroller_sha256"] == expected["carcontroller.py_sha256"] and
      state["hca_timer_reset_sha256"] is None):
    mode = "READY_TO_INSTALL"
  elif (state["carcontroller_sha256"] == deployed["carcontroller.py"] and
        state["hca_timer_reset_sha256"] == deployed["hca_timer_reset.py"]):
    mode = "PACKAGE_ALREADY_PRESENT"
  else:
    mode = "FILE_MISMATCH"

  print(json.dumps({"package_match": mode, **state}, ensure_ascii=False, indent=2))
  if state["branch"] != manifest["device_branch"] or state["commit"] != manifest["base_commit"]:
    raise RuntimeError("Device branch or commit differs from the inspected baseline")
  if mode == "FILE_MISMATCH":
    raise RuntimeError("Device files differ from both baseline and candidate; do not install")
  if state["IsOffroad"] != "1":
    if not args.parked_ignition or state["IsOffroad"] != "0":
      raise RuntimeError("Device is not confirmed offroad")
    guard = PARKED_GUARD.read_text(encoding="utf-8") + "\nrequire_parked_ignition()\n"
    subprocess.run(command[:-1] + ["cd /data/openpilot && python3 -"], input=guard,
                   text=True, capture_output=True, check=True)
  held = state["DisableUpdates"] == "1" and state["update_hold_marker"]
  if state["UpdateAvailable"] == "1" or (state["UpdateAvailable"] != "0" and not held):
    raise RuntimeError("A pending updater state may replace the package on reboot")
  if state["UpdaterState"] != "idle" and not (held and state["UpdaterState"] is None):
    raise RuntimeError("Updater is active; wait until it returns to idle")
  print("PREFLIGHT_OK")


if __name__ == "__main__":
  try:
    main()
  except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
    print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)
