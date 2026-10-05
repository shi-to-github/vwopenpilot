"""PQ HCA scheduler: opportunistic standby reset plus an unconditional fallback.

One full standby (55 frames at 50 Hz = 1.1 s) is guaranteed every cycle even when
no opportunistic window opens. The 350 s prompt only informs the driver and never
soft-disables, and the 355 s forced pause ignores every entry, geometry, driver
input and saturation gate, so the rack really receives 55 consecutive inactive
commands. The rack keeps normal power assist throughout, therefore only a real
disengage (lat_active false) may end the forced pause early.

The software counter is not the rack's internal counter. Resetting the local
timer after a forced pause says nothing about whether the rack accepted it; the
only evidence is the raw Lenkhilfe_2 (978) status after the pause resumes.
"""
import math
import time

VERSION = 'hca-r4-forced'


class HcaTimerReset:
  def __init__(self, message_hz=50, seek_after_s=180, notice_after_s=300,
               prompt_after_s=350, forced_after_s=355, backstop_after_s=400,
               standby_s=1.1, notice_s=3, quiet_s=.75, retry_s=5, steer_max=300):
    self.hz = message_hz
    self.seek = round(seek_after_s * message_hz)
    self.warn = round(notice_after_s * message_hz)
    self.prompt = round(prompt_after_s * message_hz)
    self.forced = round(forced_after_s * message_hz)
    self.backstop = round(backstop_after_s * message_hz)
    self.required = round(standby_s * message_hz)
    self.notice_required = round(notice_s * message_hz)
    # No opportunistic reservation may start once the prompt window opens.
    self.schedule_limit = self.prompt
    self.active_notice_required = self.notice_required
    self.quiet_required = round(quiet_s * message_hz)
    self.retry_required = round(retry_s * message_hz)
    self.threshold = steer_max * .30
    self.saturation_threshold = steer_max * .90
    self.saturation_required = round(.20 * message_hz)
    self.elapsed = self.quiet = self.standby = self.retry = self.off_frames = 0
    self.saturated_frames = self.notice_ticks = self.notice_wait_ticks = 0
    self.completed = self.aborted = self.natural_resets = self.notice_cancelled = 0
    self.forced_completed = self.forced_aborted = self.forced_prompts = 0
    self.cycle = 1
    self.off_confirmed = False
    self.takeover_required = False
    self.forced_prompt = self.forced_active = self.prompt_latched = False
    self.phase = 'inactive'
    self.last_abort_reason = self.start_block_reason = self.continue_reason = ''
    self.raw = self.limited = self.output = 0
    self.enabled = self.lat_active = self.driver_input = False
    self.notice_id = self.prompt_id = ''
    self.notice_acknowledged = False
    self.notice_origin = str(time.monotonic_ns())
    self.notice_seq = self.prompt_seq = 0
    self.clock_epoch = self.last_now = self.notice_started_s = None
    self.notice_kind = ''

  def notice_remaining_s(self):
    frames_left = max(0, self.active_notice_required - self.notice_ticks) / self.hz
    if self.notice_started_s is not None and self.last_now is not None:
      return max(frames_left, self.active_notice_required/self.hz - (self.last_now-self.notice_started_s), 0)
    return frames_left

  def emit(self, torque, enabled, planned=False, forced=False):
    self.output, self.enabled = torque, enabled
    finished = False
    if enabled:
      self.off_frames = 0
      self.off_confirmed = False
    else:
      self.off_frames += 1
      if self.off_frames >= self.required:
        self.elapsed = self.quiet = 0
        self.clock_epoch = None
        self.notice_kind = ''
        self.takeover_required = False
        self.forced_prompt = self.prompt_latched = False
        self.prompt_id = ''
        if not self.off_confirmed:
          finished = True
          if planned:
            self.cycle += 1
            if forced:
              self.forced_completed += 1
              self.forced_active = False
              self.phase = 'forced_reset_complete'
            else:
              self.completed += 1
              self.phase = 'reset_complete'
          else:
            self.natural_resets += 1
            self.phase = 'natural_reset' if self.lat_active else 'inactive'
          self.off_confirmed = True
        self.standby = 0
        self.saturated_frames = 0
    return torque, enabled, finished

  def cancel_notice(self, reason):
    self.notice_cancelled += 1
    self.notice_id = ''
    self.notice_kind = ''
    self.notice_acknowledged = False
    self.notice_ticks = self.notice_wait_ticks = self.quiet = 0
    self.notice_started_s = None
    self.last_abort_reason = reason
    self.retry = self.retry_required

  def abort(self, reason):
    forced = self.forced_active
    self.standby = self.quiet = self.saturated_frames = 0
    self.retry = self.retry_required
    self.forced_active = False
    self.last_abort_reason = reason
    if forced:
      self.forced_aborted += 1
      self.phase = 'forced_aborted'
    else:
      self.aborted += 1
      self.phase = 'aborted'

  def begin_pause(self, forced=False):
    self.notice_id = ''
    self.notice_acknowledged = False
    self.notice_ticks = self.notice_wait_ticks = self.saturated_frames = 0
    self.notice_started_s = None
    self.forced_active = forced
    # A pause is exactly `required` consecutive standby frames, no matter what
    # the last commanded frame happened to be.
    self.off_frames = 0
    self.standby = 1
    self.phase = 'forced_standby' if forced else 'standby'
    return self.emit(0, False, planned=True, forced=forced)

  def update(self, lat_active, requested_torque, raw_torque=None,
             window_ok=False, driver_input=False, continue_ok=None,
             window_reason='', continue_reason='', input_reason='driver_input',
             delayed_ok=False, delayed_reason='', notice_ack=False,
             notice_ready=False, now=None):
    self.lat_active, self.driver_input = lat_active, driver_input
    self.raw = requested_torque if raw_torque is None else raw_torque
    self.limited = requested_torque
    self.continue_reason = continue_reason
    self.retry = max(0, self.retry - 1)
    if lat_active or self.elapsed:
      self.elapsed += 1
    if now is not None and math.isfinite(now):
      self.last_now = now
      if self.clock_epoch is None and lat_active:self.clock_epoch = now
      if self.clock_epoch is not None:
        self.elapsed = max(self.elapsed, round(max(0, now-self.clock_epoch)*self.hz))
    # The 350 s prompt informs the driver; it must never request a soft disable,
    # otherwise lat_active would drop and the 355 s fallback could never run.
    self.forced_prompt = self.elapsed >= self.prompt
    self.takeover_required = self.elapsed >= self.backstop
    finite = math.isfinite(self.raw) and math.isfinite(requested_torque)
    enabled = finite and requested_torque != 0
    safe_output = requested_torque if finite else 0
    if not lat_active:
      if self.standby:self.abort('lateral_inactive')
      if self.notice_id:self.cancel_notice('lateral_inactive')
      self.quiet = 0
      self.phase = 'inactive'
      self.start_block_reason = 'lateral_inactive'
      return self.emit(0, False)

    if self.forced_prompt and not self.prompt_latched:
      self.prompt_latched = True
      self.prompt_seq += 1
      self.prompt_id = self.notice_origin + '-p' + str(self.prompt_seq)
      self.forced_prompts += 1

    if self.standby:
      if self.forced_active:
        # Unconditional fallback: nothing here may cut the sample short.
        self.standby += 1
        self.phase = 'forced_standby'
        return self.emit(0, False, planned=True, forced=True)
      self.saturated_frames = self.saturated_frames + 1 if finite and abs(self.raw) >= self.saturation_threshold else 0
      allowed = window_ok if continue_ok is None else continue_ok
      reason = ('deadline' if self.takeover_required else
                input_reason if driver_input else
                'nonfinite_torque' if not finite else
                'sustained_saturation' if self.saturated_frames >= self.saturation_required else
                (continue_reason or 'continuation_gate') if not allowed else '')
      if reason:
        self.abort(reason)
        return self.emit(safe_output, enabled)
      self.standby += 1
      self.phase = 'standby'
      return self.emit(0, False, planned=True)

    # Fixed-time fallback, evaluated before the opportunistic notice so a pending
    # countdown can never swallow the guaranteed sample.
    if self.elapsed >= self.forced:
      if self.notice_id:
        self.cancel_notice('forced_pause')
      return self.begin_pause(forced=True)

    if self.notice_id:
      reason = ('deadline' if self.takeover_required else
                input_reason if driver_input else
                'nonfinite_torque' if not finite else
                'notice_ui_unavailable' if not notice_ready else
                (delayed_reason or 'reserved_window_changed') if not delayed_ok else '')
      if reason:
        self.cancel_notice(reason)
      elif not self.notice_acknowledged:
        if notice_ack:
          self.notice_acknowledged = True
          self.notice_ticks = 0
          self.notice_started_s = now
          self.phase = 'countdown'
        else:
          self.notice_wait_ticks += 1
          self.phase = 'awaiting_notice'
          if self.notice_wait_ticks >= self.hz:
            self.cancel_notice('notice_not_delivered')
      else:
        self.notice_ticks += 1
        self.phase = 'countdown'
        if self.notice_remaining_s() <= 0:
          if window_ok and abs(self.raw) <= self.threshold and abs(requested_torque) <= self.threshold:
            return self.begin_pause()
          self.cancel_notice(window_reason or 'execution_window_changed')
      if self.notice_id:
        return self.emit(safe_output, enabled)

    late = self.elapsed >= self.warn
    acceptable = delayed_ok if late else window_ok
    reason = ('deadline' if self.takeover_required else
              'before_seek' if self.elapsed < self.seek else
              input_reason if driver_input else
              'nonfinite_torque' if not finite else
              'retry_backoff' if self.retry else
              (delayed_reason if late else window_reason) or 'prediction_gate' if not acceptable else
              'notice_ui_unavailable' if late and not notice_ready else
              'entry_demand_high' if not late and (abs(self.raw) > self.threshold or abs(requested_torque) > self.threshold) else
              'insufficient_time_for_reset' if self.elapsed + self.required + (self.notice_required + self.hz if late else 0) >= self.prompt else '')
    self.start_block_reason = reason
    self.quiet = min(self.quiet_required, self.quiet + 1) if not reason else 0
    if self.quiet >= self.quiet_required:
      if late:
        self.notice_seq += 1
        self.notice_id = self.notice_origin + '-' + str(self.notice_seq)
        self.notice_kind = 'reset'
        self.active_notice_required = self.notice_required
        self.notice_acknowledged = False
        self.notice_ticks = self.notice_wait_ticks = 0
        self.phase = 'awaiting_notice'
        self.quiet = 0
        return self.emit(safe_output, enabled)
      return self.begin_pause()
    self.phase = ('takeover_required' if self.takeover_required else
                  'forced_prompt' if self.forced_prompt else
                  'late_seeking' if late else 'seeking' if self.elapsed >= self.seek else 'active')
    if not reason:self.start_block_reason = 'confirming_window'
    return self.emit(safe_output, enabled)

  def status(self):
    return {'version': VERSION, 'phase': self.phase, 'elapsed_s': round(self.elapsed / self.hz, 2),
            'seek_after_s': self.seek / self.hz, 'notice_after_s': self.warn / self.hz,
            'prompt_after_s': self.prompt / self.hz, 'forced_after_s': self.forced / self.hz,
            'backstop_after_s': self.backstop / self.hz, 'takeover_after_s': self.backstop / self.hz,
            'assumed_hardware_limit_s': 360,
            'seek_in_s': max(0, self.seek-self.elapsed)/self.hz,
            'forced_in_s': max(0, self.forced-self.elapsed)/self.hz,
            'standby_s': self.required/self.hz, 'cycle': self.cycle,
            'standby_left_s': max(0, self.required-self.standby)/self.hz if self.standby else 0,
            'notice_id': self.notice_id, 'prompt_id': self.prompt_id,
            'notice_acknowledged': self.notice_acknowledged, 'notice_kind': self.notice_kind,
            'forced_pause': self.forced_active, 'forced_prompt': self.forced_prompt,
            'countdown_s': self.notice_remaining_s() if self.notice_id else 0,
            'takeover_required': self.takeover_required, 'completed': self.completed,
            'forced_completed': self.forced_completed, 'forced_aborted': self.forced_aborted,
            'forced_prompts': self.forced_prompts,
            'aborted': self.aborted, 'natural_resets': self.natural_resets,
            'notice_cancelled': self.notice_cancelled, 'off_s': self.off_frames/self.hz,
            'quiet_s': self.quiet/self.hz, 'retry_s': self.retry/self.hz,
            'start_block_reason': self.start_block_reason, 'last_abort_reason': self.last_abort_reason,
            'continue_reason': self.continue_reason, 'entry_torque_limit': self.threshold,
            'saturation_limit': self.saturation_threshold, 'saturation_s': self.saturated_frames/self.hz,
            'raw_torque': self.raw, 'limited_torque': self.limited, 'output_torque': self.output,
            'hca_enabled': self.enabled, 'lat_active': self.lat_active, 'driver_input': self.driver_input}
