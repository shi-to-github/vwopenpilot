"""PQ HCA geometry gates and detailed telemetry; cruise inputs unchanged."""

from collections import deque
import json
import math
from pathlib import Path
import os


ROOT = Path('/data/pq46')
MODE = ROOT / 'v3_mode.json'
STATUS = ROOT / 'v3_status.json'
UI_STATE = ROOT / 'hca_ui.json'
STANDBY_S = 1.1
PREDICTION_MARGIN_S = .2
PREDICTION_HORIZON_S = STANDBY_S + PREDICTION_MARGIN_S


def model_features(model, speed, start_s=0, horizon_s=PREDICTION_HORIZON_S):
  try:
    end_s = start_s + horizon_s
    times, yaw = list(model.orientationRate.t), list(model.orientationRate.z)
    if len(times) != len(yaw) or not times or max(times) < end_s:
      return {'valid': False, 'reason': 'prediction_missing'}
    if (not math.isfinite(speed) or speed < 0 or
        not all(math.isfinite(x) for x in times + yaw) or times[0] > .1 or
        any(b <= a for a, b in zip(times, times[1:]))):
      return {'valid': False, 'reason': 'prediction_invalid'}
    future = [abs(z) * max(speed, 1) for t, z in zip(times, yaw) if start_s <= t <= end_s]
    # Include the exact horizon boundary between model samples.
    for boundary in (start_s, end_s):
      for i, (a, b) in enumerate(zip(times, times[1:])):
        if a < boundary < b:
          fraction = (boundary - a) / (b - a)
          boundary_yaw = yaw[i] + fraction * (yaw[i + 1] - yaw[i])
          future.append(abs(boundary_yaw) * max(speed, 1))
          break
    if not future:
      return {'valid': False, 'reason': 'prediction_invalid'}
    if len(model.laneLines) < 3 or len(model.laneLineProbs) < 3:
      return {'valid': False, 'reason': 'lanes_missing'}
    left, right = model.laneLines[1].y[0], model.laneLines[2].y[0]
    probability = min(model.laneLineProbs[1], model.laneLineProbs[2])
    desires = list(model.meta.desireState)
    if not desires or not all(math.isfinite(x) for x in (left, right, probability, *desires)):
      return {'valid': False, 'reason': 'model_values_invalid'}
    return {'valid': True, 'reason': '', 'center_m': (left + right) / 2,
            'left_m': left, 'right_m': right, 'lane_probability': probability,
            'margin_m': min(abs(left), abs(right)),
            'future_lateral_accel_ms2': max(future), 'desire_sum': sum(desires[1:]),
            'prediction_start_s': start_s, 'prediction_end_s': end_s}
  except (AttributeError, IndexError, TypeError, ValueError):
    return {'valid': False, 'reason': 'model_schema_unavailable'}


def geometry_gate(features, continuing=False):
  if not features.get('valid'):
    return False, features.get('reason', 'model_invalid')
  if features['future_lateral_accel_ms2'] > .3:
    return False, 'future_turn_demand'
  if (features['lane_probability'] < .6 or features['left_m'] * features['right_m'] >= 0 or
      features['margin_m'] < 1.1):
    return False, 'lane_margin_or_confidence'
  # Entry requires a centered vehicle; modest drift during standby has a
  # separate tighter-than-lane-margin bound and an outward-motion check.
  if abs(features['center_m']) > (.35 if continuing else .25):
    return False, 'lane_center_error'
  if features['desire_sum'] > .05:
    return False, 'lane_change_or_turn'
  return True, 'quiet_prediction'


def motion_gate(features, rate, remaining_s, continuing=False):
  allowed, reason = geometry_gate(features, continuing)
  if not allowed:
    return allowed, reason
  if rate is None or not math.isfinite(rate):
    return False, 'motion_history_missing'
  center = features['center_m']
  outward = rate * (1 if center >= 0 else -1)
  if not continuing and abs(rate) > .12:
    return False, 'center_motion_at_entry'
  if continuing and outward > .18:
    return False, 'outward_center_motion'
  limit = .35 if continuing else .25
  if abs(center) + max(0, outward) * remaining_s > limit:
    return False, 'projected_center_margin'
  return True, 'quiet_prediction'


def model_window(model, speed):
  return geometry_gate(model_features(model, speed))


def requested_mode(now, path=MODE):
  try:
    data = json.loads(path.read_text(encoding='utf-8'))
    if 0 <= now - float(data['boot_s']) <= 3 and data['mode'] in (
        'base', 'auto', 'probe_down', 'probe_up', 'probe_recall'):
      return data['mode']
  except (OSError, KeyError, TypeError, ValueError):
    pass
  return 'base'


class Runtime:
  def __init__(self):
    from cereal import messaging
    from common.realtime import sec_since_boot
    self.clock = sec_since_boot
    self.sm = messaging.SubMaster(['modelV2', 'radarState'])
    self.mode = 'base'
    self.window_ok = self.continue_ok = self.lead_fresh = False
    self.window_reason = self.continue_reason = 'model_stale'
    self.lead = None
    self.last_write = self.last_mode = -100
    self.history = deque(maxlen=12)
    self.center_rate = None
    self.geometry = {'valid': False, 'reason': 'model_stale'}
    self.last_model_ns = 0
    self.delayed_ok = self.notice_ack = self.notice_ready = False
    self.delayed_reason = 'model_stale'
    self.delayed_geometry = {'valid': False, 'reason': 'model_stale'}

  def fresh(self, service, now, maximum):
    return (self.sm.valid[service] and self.sm.alive[service] and
            0 <= now - self.sm.logMonoTime[service] / 1e9 <= maximum)

  def update_geometry(self, model, model_ns, now, speed, remaining_s, notice_delay_s=3):
    self.geometry = model_features(model, speed, horizon_s=max(PREDICTION_MARGIN_S, remaining_s + PREDICTION_MARGIN_S))
    if model_ns != self.last_model_ns:
      self.last_model_ns = model_ns
      stamp = model_ns / 1e9
      if not self.geometry['valid']:
        self.history.clear()
        self.center_rate = None
      else:
        if self.history and (stamp <= self.history[-1][0] or stamp - self.history[-1][0] > .2):
          self.history.clear()
        self.history.append((stamp, self.geometry['center_m']))
        previous = [p for p in self.history if .15 <= stamp - p[0] <= .35]
        point = min(previous, key=lambda p: abs(stamp - p[0] - .2)) if previous else None
        self.center_rate = ((self.geometry['center_m'] - point[1]) / (stamp - point[0])
                            if point is not None else None)
    self.window_ok, self.window_reason = motion_gate(self.geometry, self.center_rate, STANDBY_S)
    self.continue_ok, self.continue_reason = motion_gate(
      self.geometry, self.center_rate, max(0, remaining_s), continuing=True)
    self.delayed_geometry = model_features(model, speed, max(0, notice_delay_s))
    # Control stays active during the three-second notice; extrapolate only
    # the standby duration, not a fictitious 4.1-second unassisted interval.
    self.delayed_ok, self.delayed_reason = motion_gate(self.delayed_geometry, self.center_rate, STANDBY_S)

  def update(self, speed, remaining_s=STANDBY_S, notice_delay_s=3, notice_id=''):
    now = self.clock()
    self.sm.update(0)
    if now - self.last_mode >= .1:
      self.mode = requested_mode(now)
      self.notice_ack = self.notice_ready = False
      try:
        ui = json.loads(UI_STATE.read_text(encoding='utf-8'))
        self.notice_ready = 0 <= now - ui['boot_s'] <= 1 and ui.get('audio_ready') is True
        self.notice_ack = (self.notice_ready and bool(notice_id) and ui.get('notice_id') == notice_id and
                           ui.get('audio_ok') is True and 0 <= now-ui['ack_boot_s'] <= 6)
      except (OSError, ValueError, KeyError, TypeError):
        pass
      self.last_mode = now
    model_fresh = self.fresh('modelV2', now, .2)
    if model_fresh:
      self.update_geometry(self.sm['modelV2'], self.sm.logMonoTime['modelV2'], now, speed, remaining_s, notice_delay_s)
    else:
      self.window_ok = self.continue_ok = False
      self.window_reason = self.continue_reason = 'model_stale'
      self.geometry = {'valid': False, 'reason': 'model_stale'}
      self.history.clear()
      self.center_rate = None
      self.last_model_ns = 0
      self.delayed_ok = False
      self.delayed_reason = 'model_stale'
      self.delayed_geometry = {'valid': False, 'reason': 'model_stale'}
    self.lead_fresh = model_fresh and self.fresh('radarState', now, .25)
    self.lead = None
    if self.lead_fresh:
      lead = self.sm['radarState'].leadOne
      self.lead = {'status': lead.status, 'distance': lead.dRel, 'lateral': lead.yRel,
                   'relative': lead.vRel, 'speed': lead.vLeadK, 'prob': lead.modelProb}
    return now

  def write_status(self, now, hca, cruise, cs):
    if now - self.last_write < .1:
      return
    self.last_write = now
    data = {'boot_s': now, 'hca': hca.status(), 'cruise': cruise.status(),
            'window_ok': self.window_ok, 'window_reason': self.window_reason,
            'continue_ok': self.continue_ok, 'continue_reason': self.continue_reason,
            'delayed_ok': self.delayed_ok, 'delayed_reason': self.delayed_reason,
            'delayed_geometry': self.delayed_geometry,
            'notice_ack': self.notice_ack, 'notice_ready': self.notice_ready,
            'geometry': self.geometry, 'center_rate_mps': self.center_rate,
            'lead_fresh': self.lead_fresh, 'lead': self.lead,
            'motor_target_kph': getattr(cs, 'pq_motor_target_kph', 0), 'actual_kph': cs.out.vEgo * 3.6,
            'driver': {k: getattr(cs.out, k, None) for k in (
              'steeringTorque', 'steeringPressed', 'steeringAngleDeg', 'steeringRateDeg',
              'leftBlinker', 'rightBlinker', 'brakePressed', 'gasPressed', 'canValid')}}
    try:
      ROOT.mkdir(mode=0o700, exist_ok=True)
      temp = STATUS.with_suffix('.tmp')
      temp.write_text(json.dumps(data, allow_nan=False), encoding='utf-8')
      os.replace(str(temp), str(STATUS))
    except (OSError, ValueError):
      pass
