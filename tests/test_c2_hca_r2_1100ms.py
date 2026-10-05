"""Local verification of 55-frame standby and matched prediction horizons."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'candidate/device-a6eed9e-v3-hca-r2-1100ms'


def load(name):
  spec=importlib.util.spec_from_file_location('r2_1100_'+name,PACKAGE/'deploy'/(name+'.py'))
  m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  return m


timer_module=load('hca_timer_reset')
runtime=load('pq46_runtime')


class DurationTests(unittest.TestCase):
  def ready(self):
    timer=timer_module.HcaTimerReset(seek_after_s=.02,quiet_s=.02,entry_window_s=.02)
    self.assertEqual(timer.update(True,40,window_ok=True,continue_ok=True),(0,False,False))
    return timer

  def test_exact_55_frames_then_resume(self):
    timer=self.ready()
    self.assertEqual(timer.required,55)
    for _ in range(53):self.assertEqual(timer.update(True,6,raw_torque=80,continue_ok=True),(0,False,False))
    self.assertEqual(timer.completed,0)
    self.assertEqual(timer.update(True,6,raw_torque=80,continue_ok=True),(0,False,True))
    self.assertEqual(timer.off_frames,55);self.assertEqual(timer.completed,1)
    self.assertEqual(timer.update(True,40,window_ok=False),(40,True,False))

  def test_54_frames_are_not_a_reset_and_restart_requires_55(self):
    timer=timer_module.HcaTimerReset()
    for _ in range(100):timer.update(True,100)
    for _ in range(54):self.assertFalse(timer.update(False,0)[2])
    self.assertGreater(timer.elapsed,0)
    timer.update(True,100)
    for _ in range(54):self.assertFalse(timer.update(False,0)[2])
    self.assertTrue(timer.update(False,0)[2]);self.assertEqual(timer.natural_resets,1)

  def test_previous_request_abort_is_preserved(self):
    timer=self.ready()
    self.assertEqual(timer.update(True,6,raw_torque=91,continue_ok=True),(6,True,False))
    self.assertEqual(timer.completed,0);self.assertEqual(timer.last_abort_reason,'large_raw_demand')

  def test_controller_passes_full_and_remaining_1100ms(self):
    import test_c2_hca_r1 as old
    oldc,cc,cs=old.IntegrationTest().fixture()
    ns=dict(oldc.update.__globals__);ns['HcaTimerReset']=timer_module.HcaTimerReset
    tree=ast.parse((PACKAGE/'deploy/carcontroller.py').read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef))
    exec(compile(ast.Module(body=[cls],type_ignores=[]),'1100_controller','exec'),ns)
    c=ns['CarController'](oldc.CP.carFingerprint,oldc.CP,None)
    c.pq_runtime.continue_ok=True
    c.pq_runtime.window_reason=c.pq_runtime.continue_reason='quiet_prediction'
    args=[]
    c.pq_runtime.update=lambda speed,remaining:args.append(remaining) or c.pq_runtime.now
    c.update(cc,cs,0);self.assertAlmostEqual(args[-1],1.1)
    c.pq_hca_timer_reset.standby=25
    c.update(cc,cs,0);self.assertAlmostEqual(args[-1],.6)


class PredictionTests(unittest.TestCase):
  def model(self):
    return NS(orientationRate=NS(t=[0,.5,1,1.2,1.5,2,2.5],z=[0]*7),
              laneLines=[NS(y=[0]),NS(y=[-1.7]),NS(y=[1.9])],
              laneLineProbs=[0,.95,.95],meta=NS(desireState=[1,0,0,0]))

  def test_late_curve_does_not_block_short_window(self):
    m=self.model();m.orientationRate.z[-2:]=[.1,.1]
    f=runtime.model_features(m,30)
    self.assertTrue(f['valid']);self.assertEqual(f['future_lateral_accel_ms2'],0)
    self.assertTrue(runtime.motion_gate(f,0,1.1)[0])

  def test_interpolated_boundary_detects_turn_before_horizon(self):
    m=self.model();m.orientationRate.z[4]=.06
    f=runtime.model_features(m,30)
    self.assertAlmostEqual(f['future_lateral_accel_ms2'],.6)
    self.assertEqual(runtime.motion_gate(f,0,1.1)[1],'future_turn_demand')

  def test_projected_motion_uses_1100ms_and_margin_is_explicit(self):
    f=runtime.model_features(self.model(),30)
    self.assertTrue(runtime.motion_gate(f,.1,runtime.STANDBY_S)[0])
    self.assertFalse(runtime.motion_gate(f,.1,2)[0])
    self.assertAlmostEqual(runtime.PREDICTION_HORIZON_S,1.3)
    self.assertAlmostEqual(runtime.STANDBY_S,timer_module.HcaTimerReset().required/50)

  def test_payload_hashes_match_pinned_rollback_and_manifest(self):
    m=json.loads((PACKAGE/'manifest.json').read_text())
    for name in m['changed']:
      remote='/data/openpilot/selfdrive/car/volkswagen/'+name
      for sub,key in (('deploy','after_sha256'),('rollback','before_sha256')):
        self.assertEqual(hashlib.sha256((PACKAGE/sub/name).read_bytes()).hexdigest(),m[key][remote])


if __name__=='__main__':unittest.main()
