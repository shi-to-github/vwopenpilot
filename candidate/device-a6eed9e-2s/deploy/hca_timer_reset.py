"""Candidate long-standby reset for PQ HCA timers.

Disabled by default. Enable only in a device-specific test commit after the
running C2 revision and message rate have been verified.
"""

PQ_LONG_STANDBY_ENABLED = True
PQ_RESET_AFTER_S = 240.0
PQ_STANDBY_S = 2.0


class HcaTimerReset:
  def __init__(self, message_hz, reset_after_s=PQ_RESET_AFTER_S, standby_s=PQ_STANDBY_S):
    self.message_hz = message_hz
    self.reset_after_frames = int(round(reset_after_s * message_hz))
    self.required_standby_frames = int(round(standby_s * message_hz))
    self.active_frames = 0
    self.standby_frames = 0
    self.forcing_standby = False

  def update(self, lat_active, requested_torque):
    if not lat_active:
      self.active_frames = 0
      self.standby_frames = 0
      self.forcing_standby = False
      return 0, False, False

    if self.forcing_standby:
      self.standby_frames += 1
      completed = self.standby_frames >= self.required_standby_frames
      if completed:
        self.active_frames = 0
        self.standby_frames = 0
        self.forcing_standby = False
      return 0, False, completed

    if requested_torque == 0:
      self.standby_frames += 1
      completed = self.standby_frames >= self.required_standby_frames
      if completed:
        self.active_frames = 0
      return 0, False, completed

    self.standby_frames = 0
    self.active_frames += 1
    if self.active_frames >= self.reset_after_frames:
      self.forcing_standby = True
      self.standby_frames = 1
      return 0, False, self.required_standby_frames == 1

    return requested_torque, True, False
