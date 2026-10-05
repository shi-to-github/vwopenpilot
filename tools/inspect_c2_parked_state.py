"""Read current C2 car/control messages; safe for a parked, running vehicle."""

import json
import time

from cereal import messaging


services = ["carState", "controlsState", "pandaStates"]
sm = messaging.SubMaster(services)
deadline = time.monotonic() + 5
while time.monotonic() < deadline and not all(sm.rcv_time[s] for s in services):
  sm.update(500)

car = sm["carState"]
controls = sm["controlsState"]
pandas = sm["pandaStates"]
print(json.dumps({
  "received": {s: bool(sm.rcv_time[s]) for s in services},
  "alive": sm.alive,
  "car": {
    "vEgo_mps": car.vEgo,
    "standstill": car.standstill,
    "gearShifter": str(car.gearShifter),
    "brakePressed": car.brakePressed,
  },
  "controls": {"enabled": controls.enabled, "active": controls.active},
  "pandas": [{"ignitionLine": p.ignitionLine, "ignitionCan": p.ignitionCan} for p in pandas],
}, ensure_ascii=False))
