"""Finite stock-cruise button pulses with ECU acknowledgements and lead trim."""

import math


BUTTONS = ('up', 'down', 'recall')
COARSE_MAX_KPH = 12.8
FINE_MAX_KPH = 2.56


class ButtonPulse:
  """Nine press frames over 180 ms, one release, then at most 2 s for ECU ack.

  Native neutral frames remain present on this topology. This is a candidate
  sequence, not proof that the ECU will accept it. No retry follows a timeout.
  """
  def __init__(self):
    self.phase = 'idle'
    self.direction = ''
    self.reason = 'idle'
    self.press_count = 0
    self.started = 0
    self.sent_at = 0
    self.before = 0
    self.done_at = -100
    self.minimum = 20
    self.maximum = 160

  def start(self, direction, target, now, minimum=20, maximum=160):
    if self.phase != 'idle' or direction not in BUTTONS:
      return False
    if not math.isfinite(target) or not 20 <= target <= 160:
      return False
    self.direction = direction
    self.minimum = minimum
    self.maximum = maximum
    self.before = target
    self.started = now
    self.press_count = 0
    self.phase = 'press'
    self.reason = 'sending_' + direction
    return True

  def fault(self, reason):
    self.phase = 'fault'
    self.reason = reason

  def update(self, now, target, allow, driver_input=False):
    if self.phase in ('idle', 'done', 'fault'):
      return
    if driver_input:
      self.fault('driver_override')
      return
    if not allow or not math.isfinite(target) or target <= 0:
      self.fault('controls_or_feedback_unavailable')
      return
    delta = target - self.before
    expected = delta <= -0.6 if self.direction == 'down' else delta >= 0.6
    if self.phase in ('press', 'release', 'wait'):
      if expected:
        maximum = COARSE_MAX_KPH if self.direction in ('up', 'down') else FINE_MAX_KPH
        if target < self.minimum - .05 or target > self.maximum + .05:
          self.fault('target_limit_exceeded')
        elif abs(delta) > maximum + 0.05:
          self.fault('unexpected_step')
        else:
          if self.phase == 'wait':
            self.phase = 'done'
            self.done_at = now
            self.reason = 'ecu_target_acknowledged'
          else:
            # Native neutral frames might make another injected frame a new
            # edge. Stop pressing as soon as a target change is observed.
            self.phase = 'release'
            self.reason = 'target_changed_releasing'
      elif abs(delta) > 0.6:
        self.fault('wrong_direction')
      elif self.phase == 'wait' and now - self.sent_at >= 2:
        self.fault('ecu_ack_timeout')
    if self.phase in ('press', 'release') and now - self.started > 0.8:
      self.fault('native_counter_or_release_timeout')

  def frame(self, now):
    if self.phase == 'release':
      self.phase = 'wait'
      self.sent_at = now
      return 'release'
    if self.phase == 'press':
      if self.press_count == 0:
        self.started = now
      # Press duration is bounded both by elapsed time and frame count.
      if self.press_count < 9 and now - self.started < 0.18:
        self.press_count += 1
        return self.direction
      if self.press_count < 6:
        self.fault('insufficient_press_frames')
        return 'release'
      self.phase = 'wait'
      self.sent_at = now
      self.reason = 'waiting_for_ecu_target'
      return 'release'
    return ''


class CruiseTrim:
  def __init__(self, minimum_kph=60):
    self.minimum = minimum_kph
    self.mode = 'base'
    self.reset()

  def reset(self):
    self.pulse = ButtonPulse()
    self.ceiling = 0
    self.desired = 0
    self.last_target = 0
    self.engaged = False
    self.stable_since = None
    self.lead_since = None
    self.clear_since = None
    self.lead_latched = False
    self.override_until = 0
    self.capture_at = None
    self.fault = ''
    self.test_used = False
    self.reason = 'inactive'
    self.manual_control_required = False

  def set_mode(self, mode):
    if mode != self.mode:
      # Switching modes cannot evade a failed command during this engagement.
      previous_fault = self.fault
      engaged = self.engaged
      self.mode = mode
      self.reset()
      self.engaged = engaged
      self.fault = previous_fault if engaged else ''

  def update(self, now, active, target, speed, feedback_fresh=True,
             can_valid=True, driver_button=False, brake=False, gas=False,
             data_fresh=False, lead=None, steer_reset=False):
    if not active or brake:
      self.reset()
      return ''
    self.engaged = True
    valid = (can_valid and feedback_fresh and math.isfinite(target) and
             20 <= target <= 160 and math.isfinite(speed))
    if not valid:
      if self.pulse.phase not in ('idle', 'done', 'fault'):
        self.pulse.fault('feedback_stale')
        self.fault = self.pulse.reason
      self.reason = 'feedback_unavailable'
      return ''
    if not self.ceiling:
      self.ceiling = self.desired = self.last_target = target
    allow = (self.mode != 'base' and valid and not gas and speed >= 70 and
             not steer_reset and (self.mode != 'auto' or data_fresh))
    self.pulse.update(now, target, allow,
                      driver_input=driver_button)
    if self.pulse.phase == 'fault':
      self.fault = self.pulse.reason
    if driver_button:
      self.override_until = now + 2
      self.capture_at = self.override_until
      self.stable_since = None
      self.reason = 'driver_button_override'
      return ''
    if self.capture_at is not None:
      if now < self.capture_at:
        return ''
      self.ceiling = self.desired = target
      self.last_target = target
      self.capture_at = None
      self.lead_latched = False
    if gas or steer_reset or speed < 70 or now < self.override_until:
      self.stable_since = None
      self.reason = 'driver_input_or_speed_or_hca_reset'
      return ''
    if self.fault:
      self.reason = self.fault
      return ''
    if self.mode == 'base':
      self.reason = 'lateral_and_logging'
      return ''
    if self.stable_since is None:
      self.stable_since = now
    if self.pulse.phase in ('press', 'release', 'wait'):
      self.reason = self.pulse.reason
      return ''
    if self.pulse.phase == 'done':
      self.last_target = target
      if now - self.pulse.done_at < 2:
        return ''
      if self.mode.startswith('probe_'):
        self.test_used = True
        self.reason = 'test_acknowledged'
        return ''
      self.pulse = ButtonPulse()
    if abs(target - self.last_target) > 0.6:
      self.fault = self.reason = 'unattributed_target_change'
      return ''
    if now - self.stable_since < 5:
      self.reason = 'waiting_for_stable_engagement'
      return ''
    direction = ''
    if self.mode.startswith('probe_') and not self.test_used:
      direction = self.mode[6:]
      if direction not in BUTTONS or (direction == 'down' and target < self.minimum + COARSE_MAX_KPH):
        self.reason = 'test_target_guard'
        return ''
      if direction != 'down' and target > 140:
        self.reason = 'test_target_guard'
        return ''
      self.test_used = True
    elif self.mode == 'auto':
      # Fresh but empty lead data may mean a clear road; missing data never does.
      if not data_fresh:
        self.lead_since = self.clear_since = None
        self.reason = 'lead_data_stale'
        return ''
      if lead is None or not all(math.isfinite(lead.get(k, float('nan')))
          for k in ('distance', 'lateral', 'relative', 'speed', 'prob')):
        self.lead_since = self.clear_since = None
        self.reason = 'lead_data_invalid'
        return ''
      if lead.get('status') and (lead['prob'] < 0.85 or abs(lead['lateral']) > 1.5 or
                                lead['speed'] < 0 or not 8 < lead['distance'] < 200):
        self.lead_since = self.clear_since = None
        self.reason = 'lead_uncertain'
        return ''
      detected = lead is not None and all(math.isfinite(lead.get(k, float('nan')))
                 for k in ('distance', 'lateral', 'relative', 'speed', 'prob'))
      detected = bool(detected and lead.get('status') and lead['prob'] >= 0.85
                      and abs(lead['lateral']) <= 1.5 and 8 < lead['distance'] < 200
                      and lead['speed'] >= 0)
      if detected:
        self.clear_since = None
        if self.lead_since is None:
          self.lead_since = now
        gap = max(15, speed / 3.6 * 3)
        closing = max(0, -lead['relative'])
        ttc = lead['distance'] / closing if closing > 0.1 else 1000
        self.manual_control_required = lead['distance'] < gap or ttc < 8
        if now - self.lead_since < 2:
          self.reason = 'confirming_lead'
          return ''
        if lead['distance'] < gap + closing * 8:
          self.lead_latched = True
          self.desired = min(self.ceiling, max(self.minimum, lead['speed'] * 3.6))
      else:
        self.lead_since = None
        if self.clear_since is None:
          self.clear_since = now
        if now - self.clear_since < 3:
          self.reason = 'confirming_clear_road'
          return ''
        self.lead_latched = False
        self.manual_control_required = False
        self.desired = self.ceiling
      if self.desired <= target - 8 and target - COARSE_MAX_KPH >= self.minimum:
        direction = 'down'
      elif (not self.manual_control_required and self.desired >= target + FINE_MAX_KPH and
            target + FINE_MAX_KPH <= self.ceiling + 0.05):
        # Never restore while a detected lead is still closing.
        if not detected or lead['relative'] >= -0.2:
          direction = 'up' if min(self.desired, self.ceiling) - target >= COARSE_MAX_KPH else 'recall'
    maximum = self.ceiling if self.mode == 'auto' else 160
    if direction and self.pulse.start(direction, target, now, self.minimum, maximum):
      self.reason = self.pulse.reason
      return direction
    self.reason = 'observing'
    return ''

  def status(self):
    return {'mode': self.mode, 'phase': self.pulse.phase, 'reason': self.reason,
            'fault': self.fault, 'direction': self.pulse.direction,
            'press_frames': self.pulse.press_count, 'ceiling_kph': round(self.ceiling, 2),
            'desired_kph': round(self.desired, 2),
            'manual_control_required': self.manual_control_required}
