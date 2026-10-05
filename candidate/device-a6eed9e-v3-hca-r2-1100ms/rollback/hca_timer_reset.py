"""PQ HCA opportunity reset with separate entry/continuation gates."""

import math
from collections import deque


VERSION = 'hca-r2-entry'


class HcaTimerReset:
  def __init__(self, message_hz=50, seek_after_s=150, standby_s=2,
               quiet_s=0.75, retry_s=5, takeover_s=240, steer_max=300,
               entry_window_s=0.4):
    self.hz = message_hz
    self.seek = round(seek_after_s * message_hz)
    self.required = round(standby_s * message_hz)
    self.quiet_required = round(quiet_s * message_hz)
    self.retry_required = round(retry_s * message_hz)
    self.deadline = round(takeover_s * message_hz)
    self.threshold = steer_max * 0.20
    self.abort_threshold = steer_max * 0.30
    self.entry_window_frames = max(1, round(entry_window_s * message_hz))
    self.entry_history = deque(maxlen=self.entry_window_frames)
    self.entry_raw_rms = self.entry_limited_rms = self.entry_peak = None
    self.elapsed = self.quiet = self.standby = self.retry = self.off_frames = 0
    self.completed = self.aborted = self.natural_resets = 0
    self.off_confirmed = False
    self.takeover_required = False
    self.phase = 'inactive'
    self.last_abort_reason = ''
    self.start_block_reason = 'inactive'
    self.continue_reason = ''
    self.raw = self.limited = self.output = 0
    self.enabled = self.lat_active = self.driver_input = False

  def emit(self, torque, enabled, planned=False):
    self.output, self.enabled = torque, enabled
    completed = False
    if enabled:
      self.off_frames = 0
      self.off_confirmed = False
    else:
      self.off_frames += 1
      if self.off_frames >= self.required:
        # Only actual consecutive HCA-disabled frames confirm a reset.
        self.elapsed = self.quiet = 0
        self.takeover_required = False
        if not self.off_confirmed:
          completed = True
          if planned:
            self.completed += 1
            self.phase = 'reset_complete'
          else:
            self.natural_resets += 1
            self.phase = 'natural_reset' if self.lat_active else 'inactive'
          self.off_confirmed = True
        self.standby = 0
    return torque, enabled, completed

  def abort(self, reason):
    self.standby = self.quiet = 0
    self.retry = self.retry_required
    self.aborted += 1
    self.last_abort_reason = reason
    self.phase = 'aborted'
    self.clear_entry_history()

  def clear_entry_history(self):
    self.entry_history.clear()
    self.entry_raw_rms = self.entry_limited_rms = self.entry_peak = None

  def observe_entry(self, raw, limited):
    self.entry_history.append((raw, limited))
    if len(self.entry_history) == self.entry_window_frames:
      self.entry_raw_rms = math.sqrt(sum(a*a for a, _ in self.entry_history) / len(self.entry_history))
      self.entry_limited_rms = math.sqrt(sum(b*b for _, b in self.entry_history) / len(self.entry_history))
      self.entry_peak = max(abs(a) for a, _ in self.entry_history)

  def update(self, lat_active, requested_torque, raw_torque=None,
             window_ok=False, driver_input=False, continue_ok=None,
             window_reason='', continue_reason='', input_reason='driver_input'):
    self.lat_active, self.driver_input = lat_active, driver_input
    self.raw = requested_torque if raw_torque is None else raw_torque
    self.limited = requested_torque
    self.continue_reason = continue_reason
    self.retry = max(0, self.retry - 1)
    if lat_active or self.elapsed:
      self.elapsed += 1
    if self.elapsed >= self.deadline:
      self.takeover_required = True
    if not lat_active:
      if self.standby:
        self.abort('lateral_inactive')
      self.quiet = 0
      self.clear_entry_history()
      self.phase = 'inactive'
      self.start_block_reason = 'lateral_inactive'
      return self.emit(0, False)

    finite = math.isfinite(self.raw) and math.isfinite(requested_torque)
    if self.standby:
      allowed = window_ok if continue_ok is None else continue_ok
      reason = ('deadline' if self.takeover_required else
                input_reason if driver_input else
                'nonfinite_torque' if not finite else
                'large_raw_demand' if abs(self.raw) > self.abort_threshold else
                (continue_reason or 'continuation_gate') if not allowed else '')
      if reason:
        self.abort(reason)
        # Caller has already limited against the last actually transmitted
        # torque, so restoring this value keeps the normal rate limits.
        return self.emit(requested_torque if finite else 0,
                         finite and requested_torque != 0)
      self.standby += 1
      self.phase = 'standby'
      return self.emit(0, False, planned=True)

    # Filter only ENTRY evidence. During standby the original immediate raw
    # request, geometry/data and driver aborts above remain unchanged.
    # Geometry gates still reset quiet confirmation below. Torque history is
    # independent evidence and can remain fresh while geometry is unsuitable.
    if not finite or driver_input or self.retry:
      self.clear_entry_history()
    else:
      self.observe_entry(self.raw, requested_torque)

    reason = ('deadline' if self.takeover_required else
              'before_seek' if self.elapsed < self.seek else
              input_reason if driver_input else
              'nonfinite_torque' if not finite else
              (window_reason or 'entry_gate') if not window_ok else
              'retry_backoff' if self.retry else
              'entry_history_missing' if self.entry_raw_rms is None else
              'entry_peak_above_abort' if self.entry_peak > self.abort_threshold else
              'entry_raw_rms_high' if self.entry_raw_rms > self.threshold else
              'entry_limited_rms_high' if self.entry_limited_rms > self.threshold else
              'insufficient_time_for_pause' if self.elapsed + self.required > self.deadline else '')
    self.start_block_reason = reason
    self.quiet = min(self.quiet_required, self.quiet + 1) if not reason else 0
    if self.quiet >= self.quiet_required:
      # A brief 60..90 request may preserve past quiet evidence, but cannot
      # start a pause. Both instantaneous requests must still be <=60.
      if abs(self.raw) <= self.threshold and abs(requested_torque) <= self.threshold:
        self.standby = 1
        self.phase = 'standby'
        self.clear_entry_history()
        return self.emit(0, False, planned=True)
      self.start_block_reason = 'waiting_instantaneous_low_torque'
    self.phase = ('takeover_required' if self.takeover_required else
                  'seeking' if self.elapsed >= self.seek else 'active')
    if not reason and self.quiet < self.quiet_required:
      self.start_block_reason = 'confirming_quiet'
    return self.emit(requested_torque if finite else 0, finite and requested_torque != 0)

  def status(self):
    return {'version': VERSION, 'phase': self.phase, 'elapsed_s': round(self.elapsed / self.hz, 2),
            'seek_in_s': round(max(0, self.seek - self.elapsed) / self.hz, 2),
            'standby_left_s': round(max(0, self.required - self.standby) / self.hz, 2)
                              if self.standby else 0,
            'takeover_required': self.takeover_required,
            'completed': self.completed, 'aborted': self.aborted,
            'natural_resets': self.natural_resets,
            'off_s': round(self.off_frames / self.hz, 2),
            'quiet_s': round(self.quiet / self.hz, 2), 'retry_s': round(self.retry / self.hz, 2),
            'start_block_reason': self.start_block_reason, 'last_abort_reason': self.last_abort_reason,
            'continue_reason': self.continue_reason,
            'entry_torque_limit': self.threshold, 'abort_torque_limit': self.abort_threshold,
            'entry_window_s': self.entry_window_frames / self.hz,
            'entry_history_samples': len(self.entry_history),
            'entry_raw_rms': self.entry_raw_rms, 'entry_limited_rms': self.entry_limited_rms,
            'entry_peak': self.entry_peak, 'seek_after_s': self.seek / self.hz,
            'raw_torque': self.raw, 'limited_torque': self.limited, 'output_torque': self.output,
            'hca_enabled': self.enabled, 'lat_active': self.lat_active, 'driver_input': self.driver_input}
