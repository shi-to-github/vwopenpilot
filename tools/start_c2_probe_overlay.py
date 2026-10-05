"""Install and show the locally built C2 floating probe switch while parked.

The Python probe package must already be installed. This command leaves test
mode OFF; only touching the floating button arms the one-shot test.
"""

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time

import manage_c2_v2_probe_package as package_manager


ROOT = pathlib.Path(__file__).resolve().parents[1]
APK = ROOT / "candidate" / "device-a6eed9e-v2-probe" / "overlay" / "build" / "pq46-probe-overlay.apk"
REMOTE_APK = "/data/local/tmp/pq46-probe-overlay.apk"


def ssh(args, command, code=None):
  return subprocess.run(package_manager.ssh_prefix(args) + [command],
                        input=code,
                        text=True, encoding="utf-8", errors="replace",
                        capture_output=True, check=True).stdout.strip()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--ip", required=True)
  parser.add_argument("--port", type=int, default=8022)
  parser.add_argument("--user", default="root")
  parser.add_argument("--identity", type=pathlib.Path,
                      default=pathlib.Path.home() / ".ssh" / "vwopenploot_c2_id_rsa")
  parser.add_argument("--known-hosts", type=pathlib.Path,
                      default=pathlib.Path.home() / ".ssh" / "known_hosts_vwopenploot_c2")
  args = parser.parse_args()
  if not APK.is_file():
    parser.error("Build the signed APK with tools/build_c2_probe_overlay.py first")

  manifest = json.loads(package_manager.PACKAGE.joinpath("manifest.json").read_text(encoding="utf-8"))
  status = json.loads(subprocess.run(
    package_manager.ssh_prefix(args) + ["cd /data/openpilot && python3 -"],
    input=("CONFIG = " + repr(manifest) + "\nACTION = 'status'\nPARKED_IGNITION = False\n" +
           package_manager.REMOTE), text=True, capture_output=True, check=True).stdout)
  if status["package_state"] != "PROBE_PRESENT" or status["IsOffroad"] not in ("0", "1"):
    raise RuntimeError("Expected the installed probe package on a powered, known C2")
  if status["probe_mode"] not in (None, "0"):
    raise RuntimeError("Test mode must be off before showing the overlay")
  if status["IsOffroad"] == "0":
    guard = (ROOT / "tools" / "c2_parked_guard.py").read_text(encoding="utf-8")
    subprocess.run(package_manager.ssh_prefix(args) + ["cd /data/openpilot && python3 -"],
                   input=guard + "\nrequire_parked_ignition()\n", text=True,
                   capture_output=True, check=True)

  scp = ["scp", "-q", "-O", "-P", str(args.port), "-i", str(args.identity),
         "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
         "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={args.known_hosts}",
         str(APK), f"{args.user}@{args.ip}:{REMOTE_APK}"]
  subprocess.run(scp, check=True)
  ssh(args, "chmod 644 " + REMOTE_APK)
  local_hash = hashlib.sha256(APK.read_bytes()).hexdigest()
  remote_hash = ssh(args, "sha256sum " + REMOTE_APK).split()[0]
  if remote_hash != local_hash:
    raise RuntimeError("APK transfer hash mismatch")
  installed = ssh(args, "LD_LIBRARY_PATH= pm install -r " + REMOTE_APK)
  if "Success" not in installed:
    raise RuntimeError("Android package installer did not confirm success: " + installed)
  ssh(args, "LD_LIBRARY_PATH= appops set nl.vwopenploot.probe SYSTEM_ALERT_WINDOW allow")
  start = '''
import os, subprocess
env = os.environ.copy()
env['PYTHONPATH'] = '/data/openpilot'
with open('/data/pq46/overlay_server.stdout', 'ab') as out, open('/data/pq46/overlay_server.stderr', 'ab') as err:
  process = subprocess.Popen(['python3', '/data/pq46/overlay_server.py'], cwd='/data/openpilot', env=env,
                             stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                             close_fds=True, start_new_session=True)
print(process.pid)
'''
  try:
    ssh(args, "curl -fsS http://127.0.0.1:8765/status")
  except subprocess.CalledProcessError:
    ssh(args, "python3 -", start)
  for _ in range(6):
    time.sleep(1)
    try:
      current = ssh(args, "curl -fsS http://127.0.0.1:8765/status")
      state = json.loads(current)
      if state.get("enabled") is False:
        break
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
      continue
  else:
    raise RuntimeError("Floating switch backend did not become healthy")
  shown = ssh(args, "LD_LIBRARY_PATH= am start -n nl.vwopenploot.probe/.OverlayActivity")
  print(installed)
  print(shown)
  print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
  try:
    main()
  except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
    print("ERROR:", error, file=sys.stderr)
    if isinstance(error, subprocess.CalledProcessError) and error.stderr:
      print(error.stderr.strip(), file=sys.stderr)
    sys.exit(1)
