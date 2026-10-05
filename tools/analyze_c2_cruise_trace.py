"""Summarize a PQ cruise JSONL trace without changing the original log."""

import argparse
import json
import pathlib


BUTTONS = ("up_short", "down_short", "up_long", "down_long", "tip_up", "tip_down",
           "recall", "set", "cancel")


def summarize(path):
  counts = {"GRA_Neu": 0, "Motor_2": 0, "ACC_GRA_Anziege": 0}
  previous_buttons = {}
  previous_set = None
  first_time = None
  latest_c2_set = None
  output = []

  with path.open("r", encoding="utf-8") as source:
    for number, line in enumerate(source, 1):
      try:
        record = json.loads(line)
      except json.JSONDecodeError:
        output.append("line %d: unreadable JSON" % number)
        continue
      t = record.get("t_mono_ns")
      if t is not None and first_time is None:
        first_time = t
      label = ("+%.2fs" % ((t - first_time) / 1e9)) if t is not None else "operator"
      kind = record.get("type")

      if kind == "carState":
        latest_c2_set = record.get("c2_cruise_set_kph")
      elif kind == "operator":
        output.append("%s: %s %s" % (label, record.get("kind", "?"),
                    record.get("note", record.get("direction", record.get("value", "")))))
      elif kind in ("can", "sendcan"):
        name = record.get("name")
        if name in counts:
          counts[name] += 1
        if name == "GRA_Neu":
          key = (kind, record.get("src"))
          pressed = {button for button in BUTTONS if record.get(button)}
          new = pressed - previous_buttons.get(key, set())
          if new:
            output.append("%s: %s bus=%s GRA %s; C2 set=%s km/h" %
                          (label, kind, record.get("src"), ",".join(sorted(new)), latest_c2_set))
          previous_buttons[key] = pressed
        elif name == "Motor_2" and kind == "can":
          value = record.get("stock_set_kph")
          if value is not None and (previous_set is None or abs(value - previous_set) >= 0.8):
            output.append("%s: Motor_2 stock set %s km/h (GRA status %s)" %
                          (label, value, record.get("gra_status")))
            previous_set = value

  return output, counts


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("trace", type=pathlib.Path)
  args = parser.parse_args()
  events, counts = summarize(args.trace)
  for event in events:
    print(event)
  print("raw frame counts:", counts)


if __name__ == "__main__":
  main()
