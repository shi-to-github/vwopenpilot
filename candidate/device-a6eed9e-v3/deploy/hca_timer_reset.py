"""PQ HCA reset: seek a quiet window after 180 s; interrupt standby on demand."""

import math


class HcaTimerReset:
  def __init__(self, message_hz=50, seek_after_s=180, standby_s=2,
               quiet_s=0.75, retry_s=5, takeover_s=240, steer_max=300):
    self.hz = message_hz
    self.seek = round(seek_after_s * message_hz)
    self.required = round(standby_s * message_hz)
    self.quiet_required = round(quiet_s * message_hz)
    self.retry_required = round(retry_s * message_hz)
    self.deadline = round(takeover_s * message_hz)
    self.threshold = steer_max * 0.10
    self.reset()

  def reset(self):
    self.elapsed = 0
    self.quiet = 0
    self.natural = 0
    self.standby = 0
    self.retry = 0
    self.completed = 0
    self.aborted = 0
    self.takeover_required = False
    self.phase = 'active'

  def update(self, lat_active, requested_torque, raw_torque=None,
             window_ok=False, driver_input=False):
    if not lat_active:
      self.reset()
      return 0, False, False
    self.elapsed += 1
    raw = requested_torque if raw_torque is None else raw_torque
    quiet = (math.isfinite(raw) and abs(raw) <= self.threshold and
             abs(requested_torque) <= self.threshold and window_ok and not driver_input)
    if self.elapsed >= self.deadline:
      self.takeover_required = True
    if self.standby:
      if not quiet or self.takeover_required:
        self.standby = 0
        self.quiet = 0
        self.retry = self.retry_required
        self.aborted += 1
        self.phase = 'aborted'
        return requested_torque, requested_torque != 0, False
      self.standby += 1
      if self.standby >= self.required:
        self.elapsed = self.quiet = self.natural = self.standby = 0
        self.takeover_required = False
        self.completed += 1
        self.phase = 'reset_complete'
        return 0, False, True
      self.phase = 'standby'
      return 0, False, False
    if requested_torque == 0:
      self.natural += 1
      if self.natural >= self.required:
        self.elapsed = self.quiet = 0
        self.takeover_required = False
        self.phase = 'natural_reset'
        return 0, False, True
    else:
      self.natural = 0
    self.retry = max(0, self.retry - 1)
    self.quiet = self.quiet + 1 if quiet and self.elapsed >= self.seek else 0
    if (self.quiet >= self.quiet_required and not self.retry and
        not self.takeover_required):
      self.standby = 1
      self.phase = 'standby'
      return 0, False, False
    self.phase = ('takeover_required' if self.takeover_required else
                  'seeking' if self.elapsed >= self.seek else 'active')
    return requested_torque, requested_torque != 0, False

  def status(self):
    return {'phase': self.phase, 'elapsed_s': round(self.elapsed / self.hz, 2),
            'seek_in_s': round(max(0, self.seek - self.elapsed) / self.hz, 2),
            'standby_left_s': round(max(0, self.required - self.standby) / self.hz, 2)
                              if self.standby else 0,
            'takeover_required': self.takeover_required,
            'completed': self.completed, 'aborted': self.aborted}
