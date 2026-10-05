"""The ignition-on path must reject motion or active control."""

import unittest
from types import SimpleNamespace

from tools.c2_parked_guard import safe_sample


class FakeSubMaster:
  def __init__(self):
    self.rcv_time = {s: 1 for s in ("carState", "controlsState", "pandaStates")}
    self.alive = {s: True for s in self.rcv_time}
    self.data = {
      "carState": SimpleNamespace(vEgo=0, standstill=True, gearShifter="park"),
      "controlsState": SimpleNamespace(enabled=False, active=False),
      "pandaStates": [SimpleNamespace(ignitionLine=True, ignitionCan=False)],
    }

  def __getitem__(self, name):
    return self.data[name]


class ParkedGuardTest(unittest.TestCase):
  def test_accepts_stationary_park_disengaged(self):
    self.assertTrue(safe_sample(FakeSubMaster()))

  def test_rejects_motion_gear_and_engagement(self):
    for field, value in (("vEgo", 0.3), ("standstill", False), ("gearShifter", "drive")):
      sm = FakeSubMaster()
      setattr(sm["carState"], field, value)
      self.assertFalse(safe_sample(sm))
    for field in ("enabled", "active"):
      sm = FakeSubMaster()
      setattr(sm["controlsState"], field, True)
      self.assertFalse(safe_sample(sm))

  def test_rejects_missing_or_stale_messages_and_ignition(self):
    sm = FakeSubMaster()
    sm.alive["carState"] = False
    self.assertFalse(safe_sample(sm))
    sm = FakeSubMaster()
    sm["pandaStates"][0].ignitionLine = False
    self.assertFalse(safe_sample(sm))


if __name__ == "__main__":
  unittest.main()
