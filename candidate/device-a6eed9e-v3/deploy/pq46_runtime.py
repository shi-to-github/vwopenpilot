"""Nonblocking model/lead input and local telemetry for the PQ46 V3 package."""

import json
import math
import os
from pathlib import Path


ROOT = Path('/data/pq46')
MODE = ROOT / 'v3_mode.json'
STATUS = ROOT / 'v3_status.json'


def model_window(model, speed):
  try:
    times = list(model.orientationRate.t)
    yaw = list(model.orientationRate.z)
    if len(times) != len(yaw) or not times or max(times) < 2.5:
      return False, 'prediction_missing'
    if (not math.isfinite(speed) or speed < 0 or
        not all(math.isfinite(x) for x in times + yaw) or
        times[0] > 0.1 or any(b <= a for a, b in zip(times, times[1:]))):
      return False, 'prediction_invalid'
    future = [(t, z) for t, z in zip(times, yaw) if 0 <= t <= 2.5]
    if not future or any(not math.isfinite(t) or not math.isfinite(z) for t, z in future):
      return False, 'prediction_invalid'
    if max(abs(z) * max(speed, 1) for _, z in future) > 0.3:
      return False, 'future_turn_demand'
    if len(model.laneLines) < 3 or len(model.laneLineProbs) < 3:
      return False, 'lanes_missing'
    left, right = model.laneLines[1].y[0], model.laneLines[2].y[0]
    probs = (model.laneLineProbs[1], model.laneLineProbs[2])
    if not all(math.isfinite(x) for x in (left, right, *probs)):
      return False, 'lanes_invalid'
    if min(probs) < 0.6 or left * right >= 0 or min(abs(left), abs(right)) < 1.1:
      return False, 'lane_margin_or_confidence'
    if abs((left + right) / 2) > 0.25:
      return False, 'lane_center_error'
    desires = list(model.meta.desireState)
    if not desires or not all(math.isfinite(x) for x in desires) or sum(desires[1:]) > 0.05:
      return False, 'lane_change_or_turn'
    return True, 'quiet_prediction'
  except (AttributeError, IndexError, TypeError, ValueError):
    return False, 'model_schema_unavailable'


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
    self.window_ok = False
    self.window_reason = 'model_stale'
    self.lead_fresh = False
    self.lead = None
    self.last_write = -100
    self.last_mode = -100

  def fresh(self, service, now, maximum):
    return (self.sm.valid[service] and self.sm.alive[service] and
            0 <= now - self.sm.logMonoTime[service] / 1e9 <= maximum)

  def update(self, speed):
    now = self.clock()
    self.sm.update(0)
    if now - self.last_mode >= 0.1:
      self.mode = requested_mode(now)
      self.last_mode = now
    model_fresh = self.fresh('modelV2', now, 0.2)
    self.window_ok, self.window_reason = (model_window(self.sm['modelV2'], speed)
                                         if model_fresh else (False, 'model_stale'))
    self.lead_fresh = model_fresh and self.fresh('radarState', now, 0.25)
    self.lead = None
    if self.lead_fresh:
      lead = self.sm['radarState'].leadOne
      self.lead = {'status': lead.status, 'distance': lead.dRel, 'lateral': lead.yRel,
                   'relative': lead.vRel, 'speed': lead.vLeadK, 'prob': lead.modelProb}
    return now

  def write_status(self, now, hca, cruise, cs):
    if now - self.last_write < 0.1:
      return
    self.last_write = now
    data = {'boot_s': now, 'hca': hca.status(), 'cruise': cruise.status(),
            'window_ok': self.window_ok, 'window_reason': self.window_reason,
            'lead_fresh': self.lead_fresh, 'lead': self.lead,
            'motor_target_kph': getattr(cs, 'pq_motor_target_kph', 0),
            'actual_kph': cs.out.vEgo * 3.6}
    try:
      ROOT.mkdir(mode=0o700, exist_ok=True)
      temp = STATUS.with_suffix('.tmp')
      temp.write_text(json.dumps(data, allow_nan=False), encoding='utf-8')
      os.replace(str(temp), str(STATUS))
    except (OSError, ValueError):
      # Telemetry failure must not crash the vehicle's control loop.
      pass
