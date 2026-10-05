"""Temporarily hold C2 updates during an HCA test, restoring the prior setting later.

Status is read-only. Pause/resume require explicit --action values.
"""

import argparse
import pathlib
import subprocess
import sys

PARKED_GUARD = pathlib.Path(__file__).with_name("c2_parked_guard.py")


REMOTE = r'''
import json, pathlib, psutil, time
from common.params import Params

params = Params()
stage = pathlib.Path('/data/pq46_hca_staging')
marker = stage / 'update-hold.json'

def state():
  return {
    'IsOffroad': params.get_bool('IsOffroad'),
    'UpdateAvailable': params.get_bool('UpdateAvailable'),
    'UpdaterState': params.get('UpdaterState', encoding='utf-8'),
    'DisableUpdates': params.get_bool('DisableUpdates'),
    'held_by_this_tool': marker.exists(),
  }

if ACTION == 'status':
  print(json.dumps(state()))
elif ACTION == 'pause':
  before = state()
  if not before['IsOffroad']:
    if not PARKED_IGNITION:
      raise RuntimeError('C2 must be offroad or use guarded parked ignition')
    require_parked_ignition()
  if before['UpdateAvailable']:
    raise RuntimeError('C2 has a pending update')
  if before['UpdaterState'] not in ('checking...', 'idle'):
    raise RuntimeError('Updater is changing files; refusing to interrupt it')
  if marker.exists():
    if not before['DisableUpdates']:
      raise RuntimeError('Hold marker exists but updates are enabled')
    print(json.dumps(state()))
  else:
    if before['DisableUpdates']:
      raise RuntimeError('Updates were disabled outside this tool')
    stage.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker.write_text(json.dumps({'previous_DisableUpdates': False}))
    params.put_bool('DisableUpdates', True)
    for process in psutil.process_iter(['pid', 'name', 'cmdline']):
      try:
        command = process.info['cmdline'] or []
        if process.info['name'] == 'selfdrive.updated' or 'selfdrive.updated' in command:
          children = process.children(recursive=True)
          for child in children:
            child.terminate()
          process.terminate()
          _, alive = psutil.wait_procs(children + [process], timeout=3)
          for remaining in alive:
            remaining.kill()
      except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    params.put('UpdaterState', 'idle')
    time.sleep(1)
    after = state()
    if not after['DisableUpdates'] or after['UpdaterState'] != 'idle':
      raise RuntimeError('Failed to hold updater; inspect device before installing')
    print(json.dumps(after))
elif ACTION == 'resume':
  if not params.get_bool('IsOffroad'):
    if not PARKED_IGNITION:
      raise RuntimeError('C2 must be offroad or use guarded parked ignition')
    require_parked_ignition()
  if not marker.is_file():
    raise RuntimeError('No update hold marker found; refusing to change user settings')
  module = pathlib.Path('/data/openpilot/selfdrive/car/volkswagen/hca_timer_reset.py')
  if module.exists():
    raise RuntimeError('HCA candidate module is still installed; roll back first')
  previous = json.loads(marker.read_text())['previous_DisableUpdates']
  params.put_bool('DisableUpdates', bool(previous))
  marker.unlink()
  print(json.dumps(state()))
else:
  raise RuntimeError('Unsupported action')
'''


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--ip", required=True)
  parser.add_argument("--port", type=int, default=8022)
  parser.add_argument("--user", default="root")
  parser.add_argument("--identity", type=pathlib.Path,
                      default=pathlib.Path.home() / ".ssh" / "vwopenploot_c2_id_rsa")
  parser.add_argument("--known-hosts", type=pathlib.Path,
                      default=pathlib.Path.home() / ".ssh" / "known_hosts_vwopenploot_c2")
  parser.add_argument("--action", choices=("status", "pause", "resume"), default="status")
  parser.add_argument("--parked-ignition", action="store_true",
                      help="Allow ignition-on changes only with live Park/standstill/disengaged checks")
  args = parser.parse_args()
  command = [
    "ssh", "-p", str(args.port), "-i", str(args.identity),
    "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=yes",
    "-o", f"UserKnownHostsFile={args.known_hosts}",
    f"{args.user}@{args.ip}", "cd /data/openpilot && python3 -",
  ]
  guard = PARKED_GUARD.read_text(encoding="utf-8")
  code = (f"ACTION = {args.action!r}\nPARKED_IGNITION = {args.parked_ignition!r}\n"
          + guard + "\n" + REMOTE)
  result = subprocess.run(command, input=code, text=True, capture_output=True, check=True)
  print(result.stdout.strip())


if __name__ == "__main__":
  try:
    main()
  except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
    if isinstance(error, subprocess.CalledProcessError) and error.stderr:
      print(error.stderr.strip(), file=sys.stderr)
    else:
      print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)
