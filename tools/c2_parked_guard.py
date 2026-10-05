"""Confirm a powered C2 remains in Park with openpilot disengaged."""

import time


SERVICES = ("carState", "controlsState", "pandaStates")


def safe_sample(sm):
  if not all(sm.rcv_time[s] and sm.alive[s] for s in SERVICES):
    return False
  car = sm["carState"]
  controls = sm["controlsState"]
  pandas = sm["pandaStates"]
  return (abs(car.vEgo) < 0.05 and car.standstill and
          str(car.gearShifter) == "park" and
          not controls.enabled and not controls.active and
          bool(pandas) and all(p.ignitionLine or p.ignitionCan for p in pandas))


def require_parked_ignition(seconds=5):
  from cereal import messaging

  sm = messaging.SubMaster(list(SERVICES))
  deadline = time.monotonic() + seconds
  valid_samples = 0
  while time.monotonic() < deadline:
    sm.update(500)
    if all(sm.rcv_time[s] for s in SERVICES):
      if not safe_sample(sm):
        raise RuntimeError("Live C2 data do not confirm Park, standstill and disengaged controls")
      valid_samples += 1
  if valid_samples < 10:
    raise RuntimeError("Insufficient live C2 samples to confirm a parked vehicle")
