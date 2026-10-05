"""Offline model of a long-standby HCA timer reset.

This module is deliberately independent of openpilot/dragonpilot. It sends no
CAN traffic and is not a deployable vehicle controller. A version-specific
adapter must map the returned enabled/torque values to the correct Volkswagen
CAN implementation after the actual C2 source revision is identified.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class HcaOutput:
  enabled: bool
  torque: int
  forced_standby: bool
  reset_completed: bool
  active_elapsed_s: float
  standby_elapsed_s: float


class HcaTimerResetModel:
  def __init__(self, control_hz=50, reset_after_s=240.0, standby_s=2.0):
    if control_hz <= 0:
      raise ValueError("control_hz must be positive")
    if reset_after_s <= 0 or standby_s <= 0:
      raise ValueError("timings must be positive")

    self.control_hz = int(control_hz)
    self.reset_after_frames = round(reset_after_s * self.control_hz)
    self.required_standby_frames = round(standby_s * self.control_hz)
    self._active_frames = 0
    self._natural_standby_frames = 0
    self._forced_standby_frames = 0
    self._forcing = False

  @property
  def active_elapsed_s(self):
    return self._active_frames / self.control_hz

  def _output(self, enabled, torque, forced, completed=False):
    standby_frames = self._forced_standby_frames if forced else self._natural_standby_frames
    return HcaOutput(enabled, torque, forced, completed,
                     self._active_frames / self.control_hz,
                     standby_frames / self.control_hz)

  def update(self, lat_active, requested_torque):
    """Advance one Volkswagen steering-message interval."""
    if not lat_active:
      self._active_frames = 0
      self._natural_standby_frames = 0
      self._forced_standby_frames = 0
      self._forcing = False
      return self._output(False, 0, False)

    if self._forcing:
      self._forced_standby_frames += 1
      completed = self._forced_standby_frames >= self.required_standby_frames
      result = self._output(False, 0, True, completed)
      if completed:
        self._active_frames = 0
        self._natural_standby_frames = 0
        self._forced_standby_frames = 0
        self._forcing = False
      return result

    if requested_torque == 0:
      self._natural_standby_frames += 1
      if self._natural_standby_frames >= self.required_standby_frames:
        self._active_frames = 0
      return self._output(False, 0, False,
                          self._natural_standby_frames == self.required_standby_frames)

    self._natural_standby_frames = 0
    self._active_frames += 1
    if self._active_frames >= self.reset_after_frames:
      self._forcing = True
      self._forced_standby_frames = 1
      completed = self.required_standby_frames == 1
      result = self._output(False, 0, True, completed)
      if completed:
        self._active_frames = 0
        self._forced_standby_frames = 0
        self._forcing = False
      return result

    return self._output(True, int(requested_torque), False)

