"""Check diagnostic distinction between requested and applied steering."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'candidate/device-a6eed9e-v3-hca-r1-diag1/deploy/v3_capture.py'
tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
functions = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
                            and n.name in ('state_record', 'session_metadata')], type_ignores=[])
scope = {'TRACE_VERSION': 'hca-r1-diag1', 'STATE_INTERVAL_NS': {'controlsState': 50_000_000}}
exec(compile(functions, str(SOURCE), 'exec'), scope)


class Values(NS):
  def to_dict(self): return vars(self)


class Diagnostics(unittest.TestCase):
  def test_records_pid_components_and_alert(self):
    pid = Values(p=.2, i=.1, f=.03, output=.33, angleError=.5)
    lateral = NS(which=lambda:'pidState', pidState=pid)
    state = NS(enabled=True, active=True, desiredCurvature=.001, desiredCurvatureRate=0,
               curvature=.001, alertText1='Take control', alertText2='',
               alertType='steerTempUnavailable', canErrorCounter=0,
               state='softDisabling', lateralControlState=lateral)
    result = scope['state_record'](NS(logMonoTime=123, valid=True, controlsState=state), 'controlsState')
    self.assertEqual(result['lateral']['state']['i'], .1)
    self.assertEqual(result['alertType'], 'steerTempUnavailable')
    self.assertEqual(json.loads(json.dumps(result))['control_state'], 'softDisabling')

  def test_requested_and_applied_are_separate_during_standby(self):
    state = NS(enabled=True, latActive=True, longActive=False,
               actuators=Values(steer=.33, steerOutputCan=0),
               actuatorsOutput=Values(steer=0, steerOutputCan=0),
               cruiseControl=NS(cancel=False,resume=False))
    result = scope['state_record'](NS(logMonoTime=123, valid=True, carControl=state), 'carControl')
    self.assertEqual(result['requested']['steer'], .33)
    self.assertEqual(result['applied']['steer'], 0)
    self.assertTrue(result['latActive'])

  def test_metadata_contains_tuning_and_omits_private_fields(self):
    cp = NS(carFingerprint='SHARAN', lateralTuning=NS(which=lambda:'pid', pid=Values(kpV=[.6])),
            steerRatio=15.6, steerActuatorDelay=.1, minSteerSpeed=13.89,
            openpilotLongitudinalControl=False, carVin='private')
    scope['Params'] = lambda:NS(get=lambda key:b'example')
    scope['car'] = NS(CarParams=NS(from_bytes=lambda raw:cp))
    result = scope['session_metadata']()
    self.assertEqual(result['car']['lateral_tuning'], 'pid')
    self.assertNotIn('carVin', result['car'])
    self.assertNotIn('private', json.dumps(result))

  def test_missing_metadata_does_not_stop_capture(self):
    def fail(): raise RuntimeError('params unavailable')
    scope['Params'] = fail
    self.assertEqual(scope['session_metadata']()['metadata_error'], 'RuntimeError')


if __name__ == '__main__': unittest.main()
