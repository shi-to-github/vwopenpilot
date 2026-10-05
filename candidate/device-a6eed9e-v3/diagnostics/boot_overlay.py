"""Start the optional overlay backend/UI when the EON UI starts.

Every fresh server starts in base mode. This helper does not arm speed control.
"""

import os
import subprocess
import time
from urllib.request import urlopen


def healthy():
  try:
    with urlopen("http://127.0.0.1:8766/status", timeout=1) as response:
      return response.status == 200
  except Exception:
    return False


def main():
  if not healthy():
    env = os.environ.copy()
    env["PYTHONPATH"] = "/data/openpilot"
    with open("/data/pq46/v3_server.stdout", "ab") as out, \
         open("/data/pq46/v3_server.stderr", "ab") as err:
      subprocess.Popen(["python3", "/data/pq46/v3_server.py"],
                       cwd="/data/openpilot", env=env,
                       stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                       close_fds=True, start_new_session=True)
    for _ in range(20):
      if healthy():
        break
      time.sleep(0.25)
  if healthy():
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = ""
    for _ in range(30):
      try:
        completed = subprocess.run(["getprop", "sys.boot_completed"], env=env,
                                   capture_output=True, timeout=2, check=False)
        if completed.stdout.strip() == b"1":
          break
      except (OSError, subprocess.TimeoutExpired):
        pass
      time.sleep(2)
    for _ in range(20):
      try:
        result = subprocess.run(
          ["am", "start", "-n", "nl.vwopenploot.probe/.OverlayActivity"],
          env=env, capture_output=True, timeout=8, check=False)
        print("am start:", result.returncode, result.stdout.decode(errors="replace"),
              result.stderr.decode(errors="replace"), flush=True)
        if result.returncode == 0:
          return
      except (OSError, subprocess.TimeoutExpired):
        pass
      time.sleep(3)
    raise RuntimeError("Overlay activity did not start after Android became ready")


if __name__ == "__main__":
  main()
