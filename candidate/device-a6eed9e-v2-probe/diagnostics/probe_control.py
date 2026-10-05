"""Operator switch for the disabled-by-default PQ cruise button probe.

Use from a passenger-operated terminal. A press request expires after five
seconds and the controller still applies its own engagement and speed gates.
"""

import argparse
import json
import os
import pathlib
import time


ROOT = pathlib.Path("/data/pq46")
MODE = ROOT / "stock_cruise_probe_mode"
COMMAND = ROOT / "stock_cruise_probe_command"
EVENTS = ROOT / "probe_control_events.jsonl"
MODES = {"v1": 0, "observe": 1, "manual": 2}


def event(kind, **details):
  record = {"kind": kind, "unix_ns": time.time_ns(), **details}
  line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
  fd = os.open(str(EVENTS), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
  try:
    os.write(fd, line)
  finally:
    os.close(fd)
  print(json.dumps(record, ensure_ascii=False))


def current_mode():
  try:
    return int(MODE.read_text(encoding="utf-8").strip())
  except (OSError, ValueError):
    return 0


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  actions = parser.add_subparsers(dest="action", required=True)
  actions.add_parser("status")
  mode = actions.add_parser("mode")
  mode.add_argument("value", choices=MODES)
  press = actions.add_parser("press")
  press.add_argument("direction", choices=("up", "down"))
  mark = actions.add_parser("mark")
  mark.add_argument("note", help="Short observed instrument or vehicle behavior")
  args = parser.parse_args()
  ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)

  if args.action == "status":
    print(json.dumps({"mode": current_mode(), "pending_command": COMMAND.is_file()}))
  elif args.action == "mode":
    value = MODES[args.value]
    temporary = MODE.with_name(MODE.name + ".tmp")
    temporary.write_text(str(value) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(MODE))
    if value != 2 and COMMAND.exists():
      COMMAND.unlink()
    event("mode", value=args.value, numeric=value)
  elif args.action == "press":
    if current_mode() != 2:
      parser.error("manual mode must be selected first")
    if COMMAND.exists():
      parser.error("a previous command is still pending; wait for C2 to consume it")
    record = {"direction": args.direction, "created_unix_ns": time.time_ns()}
    fd = os.open(str(COMMAND), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
      os.write(fd, json.dumps(record, separators=(",", ":")).encode("utf-8"))
    finally:
      os.close(fd)
    event("press_requested", direction=args.direction,
          note="request only; sendcan and Motor_2 must confirm what happened")
  elif args.action == "mark":
    event("manual_observation", note=args.note[:160])


if __name__ == "__main__":
  main()
