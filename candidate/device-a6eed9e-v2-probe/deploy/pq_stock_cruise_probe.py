"""Disabled-by-default, one-shot PQ stock cruise button probe."""

from enum import IntEnum
import json
from pathlib import Path
import time


MODE_PATH = "/data/pq46/stock_cruise_probe_mode"
COMMAND_PATH = "/data/pq46/stock_cruise_probe_command"
HEARTBEAT_PATH = "/data/pq46/auto_probe_heartbeat"


class ProbeMode(IntEnum):
  v1 = 0
  observe = 1
  manual_once = 2
  auto_once = 3


def read_mode(path=MODE_PATH):
  try:
    mode = ProbeMode(int(Path(path).read_text(encoding="utf-8").strip()))
    if mode == ProbeMode.auto_once:
      age_ns = time.time_ns() - Path(HEARTBEAT_PATH).stat().st_mtime_ns
      if not 0 <= age_ns <= 3_000_000_000:
        return ProbeMode.v1
    return mode
  except (OSError, ValueError):
    return ProbeMode.v1


def consume_command(path=COMMAND_PATH, now_ns=None):
  command_path = Path(path)
  try:
    raw = command_path.read_text(encoding="utf-8")
    command_path.unlink()
    command = json.loads(raw)
    age_ns = (time.time_ns() if now_ns is None else now_ns) - command["created_unix_ns"]
    if command.get("direction") in ("up", "down") and 0 <= age_ns <= 5_000_000_000:
      return command["direction"]
  except (OSError, ValueError, TypeError, KeyError):
    return ""
  return ""


class StockCruiseProbe:
  def __init__(self, mode=ProbeMode.v1, hz=100):
    self.mode = ProbeMode(mode)
    self.hz = hz
    self.engaged = False
    self.pending = False
    self.pending_frames = 0
    self.waiting = False
    self.ack_frames = 0
    self.before_kph = 0.0
    self.direction = ""
    self.stable_frames = 0
    self.sent_this_engagement = False
    self.faulted = False
    self.reason = "v1"

  def reset_engagement(self):
    self.engaged = False
    self.pending = False
    self.pending_frames = 0
    self.waiting = False
    self.ack_frames = 0
    self.direction = ""
    self.stable_frames = 0
    self.sent_this_engagement = False
    self.faulted = False
    self.reason = "stock cruise inactive"

  def update(self, active, set_speed_kph, v_ego_kph, brake_pressed=False,
             gas_pressed=False, driver_button_active=False, command=""):
    if not active:
      previously_sent = self.sent_this_engagement if self.mode == ProbeMode.auto_once else False
      previously_faulted = self.faulted if self.mode == ProbeMode.auto_once else False
      self.reset_engagement()
      self.sent_this_engagement = previously_sent
      self.faulted = previously_faulted
      return False
    if self.mode == ProbeMode.v1:
      self.reason = "v1"
      return False

    self.engaged = True
    if set_speed_kph < 0 or set_speed_kph > 250:
      self.pending = False
      self.reason = "invalid setpoint"
      return False
    minimum_kph = 70 if self.mode == ProbeMode.auto_once else 55
    if brake_pressed or gas_pressed or driver_button_active or v_ego_kph < minimum_kph:
      self.pending = False
      self.stable_frames = 0
      self.reason = "driver input or speed guard"
      return False

    if self.waiting:
      if self.before_kph > 0 and set_speed_kph > 0 and (
          (self.direction == "down" and set_speed_kph <= self.before_kph - 0.5) or
          (self.direction == "up" and set_speed_kph >= self.before_kph + 0.5)):
        self.waiting = False
        self.reason = "setpoint acknowledged"
      else:
        self.ack_frames += 1
        if self.ack_frames >= round(1.5 * self.hz):
          self.waiting = False
          self.faulted = True
          self.reason = ("C2 setpoint unavailable; check Motor_2 and instrument" if self.before_kph <= 0
                         else "setpoint acknowledgement timeout")
      return False

    if self.pending:
      self.pending_frames += 1
      if self.pending_frames >= self.hz:
        self.pending = False
        self.faulted = True
        self.reason = "stock GRA counter did not advance"
      return self.pending

    if (self.mode == ProbeMode.manual_once and command in ("up", "down") and
        not self.sent_this_engagement and not self.faulted):
      self.pending = True
      self.pending_frames = 0
      self.direction = command
      self.reason = "one %s short press requested" % command.upper()
      return True

    if self.mode == ProbeMode.auto_once and not self.sent_this_engagement and not self.faulted:
      self.stable_frames += 1
      if self.stable_frames >= 5 * self.hz:
        self.pending = True
        self.pending_frames = 0
        self.direction = "down"
        self.reason = "automatic one-shot DOWN requested"
        return True

    self.reason = "observing"
    return False

  def mark_sent(self, set_speed_kph):
    if not self.pending:
      return False
    self.pending = False
    self.waiting = True
    self.ack_frames = 0
    self.before_kph = set_speed_kph
    self.sent_this_engagement = True
    self.reason = "waiting for setpoint acknowledgement"
    return True
