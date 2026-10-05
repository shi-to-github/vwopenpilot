"""Passive PQ cruise trace: raw buttons, engine setpoint, C2 state, and commands.

This process never sends CAN. It intentionally omits GPS, cameras, and VIN.
Run it for one supervised test session and keep the resulting JSONL file.
"""

import argparse
import json
import pathlib
import signal
import time

from cereal import messaging, car
from common.params import Params


GRA_NEU = 906
MOTOR_2 = 648
ACC_GRA_ANZEIGE = 1386
ADDRESSES = {GRA_NEU, MOTOR_2, ACC_GRA_ANZEIGE, 210, 978}
TRACE_VERSION = 'hca-r1-diag1'
SERVICES = ("can", "sendcan", "carState", "controlsState", "radarState", "pandaStates",
            "carControl", "liveParameters")
STATE_INTERVAL_NS = {'controlsState': 50_000_000, 'carControl': 50_000_000,
                     'liveParameters': 500_000_000}
OPERATOR_EVENTS = pathlib.Path("/data/pq46/v3_events.jsonl")
RUNTIME_STATUS = pathlib.Path('/data/pq46/v3_status.json')


def decode_frame(address, data):
  if address == 210 and len(data) == 5:
    return {'name': 'HCA_1', 'hca_status': data[1] >> 4,
            'torque_cnm': ((data[2] | ((data[3] & 127) << 8)) / 32) * (-1 if data[3] & 128 else 1)}
  if address == 978 and len(data) >= 3:
    return {'name': 'Lenkhilfe_2', 'eps_hca_status': data[2] & 15}
  if address == GRA_NEU and len(data) >= 4:
    return {
      "name": "GRA_Neu", "counter": (data[2] >> 4) & 15,
      "sender": (data[2] >> 2) & 3,
      "cancel": bool(data[1] & 2), "set": bool(data[2] & 1),
      "up_short": bool(data[1] & 8), "down_short": bool(data[1] & 4),
      "up_long": bool(data[1] & 32), "down_long": bool(data[1] & 16),
      "recall": bool(data[2] & 2),
      "tip_up": bool(data[3] & 2), "tip_down": bool(data[3] & 1),
    }
  if address == MOTOR_2 and len(data) >= 5:
    return {
      "name": "Motor_2", "gra_status": (data[2] >> 6) & 3,
      "stock_set_kph": round(data[4] * 1.28, 2),
      "motor_byte3_candidate_kph": round(data[3] * 1.28, 2),
    }
  if address == ACC_GRA_ANZEIGE and len(data) >= 4:
    return {"name": "ACC_GRA_Anziege", "acc_display_set_kph": data[3]}
  return {}


def frame_record(event, service, frame):
  data = bytes(frame.dat)
  return {"t_mono_ns": event.logMonoTime, "type": service,
          "address": frame.address, "src": frame.src, "data": data.hex(),
          **decode_frame(frame.address, data)}


def state_record(event, service):
  state = getattr(event, service)
  record = {"t_mono_ns": event.logMonoTime, "type": service, 'message_valid': event.valid}
  if service == "carState":
    record.update({
      "vEgo_kph": round(state.vEgo * 3.6, 2),
      "c2_cruise_set_kph": round(state.cruiseState.speed * 3.6, 2),
      "cruise_enabled": state.cruiseState.enabled,
      "brake": state.brakePressed, "gas": state.gasPressed,
      "button_events": [str(button.type) for button in state.buttonEvents if button.pressed],
      'steeringAngleDeg': state.steeringAngleDeg, 'steeringRateDeg': state.steeringRateDeg,
      'steeringTorque': state.steeringTorque, 'steeringPressed': state.steeringPressed,
      'yawRate': state.yawRate, 'canValid': state.canValid,
      'steerFaultTemporary': state.steerFaultTemporary,
      'steerFaultPermanent': state.steerFaultPermanent,
    })
  elif service == "controlsState":
    record.update({"controls_enabled": state.enabled, "controls_active": state.active})
    for key in ('desiredCurvature', 'desiredCurvatureRate', 'curvature',
                'alertText1', 'alertText2', 'alertType', 'canErrorCounter'):
      record[key] = getattr(state, key)
    record['control_state'] = str(state.state)
    lateral = state.lateralControlState
    kind = lateral.which()
    record['lateral'] = {'type': kind, 'state': getattr(lateral, kind).to_dict()}
  elif service == 'carControl':
    record.update({'enabled': state.enabled, 'latActive': state.latActive,
                   'longActive': state.longActive,
                   'requested': state.actuators.to_dict(),
                   'applied': state.actuatorsOutput.to_dict(),
                   'cancel': state.cruiseControl.cancel, 'resume': state.cruiseControl.resume})
  elif service == 'liveParameters':
    keys = ('valid', 'sensorValid', 'angleOffsetDeg', 'angleOffsetAverageDeg',
            'steerRatio', 'stiffnessFactor', 'roll')
    record['parameters'] = {key: getattr(state, key) for key in keys}
  elif service == "radarState":
    lead = state.leadOne
    record.update({"lead_status": lead.status, "lead_distance_m": round(lead.dRel, 2),
                   "lead_relative_ms": round(lead.vRel, 2), 'lead_lateral_m': lead.yRel,
                   'lead_speed_ms': lead.vLeadK, 'lead_probability': lead.modelProb})
  elif service == 'pandaStates':
    keys = ('safetyTxBlocked', 'controlsAllowed', 'safetyModel', 'safetyParam', 'pandaType')
    record['pandas'] = [{k: v for k, v in panda.to_dict().items() if k in keys} for panda in state]
  return record


def session_metadata():
  result = {'trace_version': TRACE_VERSION, 'passive_only': True,
            'state_interval_ns': STATE_INTERVAL_NS, 'default_state_interval_ns': 100_000_000}
  try:
    raw = Params().get('CarParams')
    if raw is not None:
      cp = car.CarParams.from_bytes(raw)
      kind = cp.lateralTuning.which()
      result['car'] = {'fingerprint': cp.carFingerprint, 'lateral_tuning': kind,
                       'tuning': getattr(cp.lateralTuning, kind).to_dict(),
                       'steerRatio': cp.steerRatio, 'steerActuatorDelay': cp.steerActuatorDelay,
                       'minSteerSpeed': cp.minSteerSpeed,
                       'openpilotLongitudinalControl': cp.openpilotLongitudinalControl}
  except Exception as error:
    # A missing optional session annotation must not stop raw CAN capture.
    result['metadata_error'] = type(error).__name__
  return result


def write_record(output, record):
  output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--seconds", type=int, default=1800)
  parser.add_argument("--output", type=pathlib.Path, required=True)
  args = parser.parse_args()
  stopped = [False]
  signal.signal(signal.SIGINT, lambda *_: stopped.__setitem__(0, True))
  signal.signal(signal.SIGTERM, lambda *_: stopped.__setitem__(0, True))
  if not 1 <= args.seconds <= 3600:
    parser.error("seconds must be between 1 and 3600")

  args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
  poller = messaging.Poller()
  sockets = [messaging.sub_sock(service, poller=poller, conflate=service not in ("can", "sendcan"))
             for service in SERVICES]
  deadline = time.monotonic() + args.seconds
  last_state = {service: 0 for service in SERVICES[2:]}
  operator_input = OPERATOR_EVENTS.open("r", encoding="utf-8") if OPERATOR_EVENTS.is_file() else None
  if operator_input is not None:
    operator_input.seek(0, 2)

  try:
    with args.output.open("x", encoding="utf-8", buffering=1) as output:
      write_record(output, {"type": "session", "started_unix_ns": time.time_ns(),
                            "duration_s": args.seconds, "raw_addresses": sorted(ADDRESSES),
                            **session_metadata()})
      previous_status = None
      while not stopped[0] and time.monotonic() < deadline:
        for socket in poller.poll(20):
          for event in messaging.drain_sock(socket):
            service = event.which()
            if service in ("can", "sendcan"):
              for frame in getattr(event, service):
                if frame.address in ADDRESSES:
                  write_record(output, frame_record(event, service, frame))
            elif event.logMonoTime - last_state[service] >= STATE_INTERVAL_NS.get(service, 100_000_000):
              write_record(output, state_record(event, service))
              last_state[service] = event.logMonoTime

        try:
          status = RUNTIME_STATUS.read_text(encoding='utf-8')
          if status != previous_status:
            data = json.loads(status)
            write_record(output, {'type': 'pq46_status', 't_mono_ns': round(data['boot_s'] * 1e9), **data})
            previous_status = status
        except (OSError, ValueError, KeyError):
          pass

        if operator_input is None and OPERATOR_EVENTS.is_file():
          operator_input = OPERATOR_EVENTS.open("r", encoding="utf-8")
        if operator_input is not None:
          for line in operator_input.readlines():
            try:
              write_record(output, {"type": "operator", **json.loads(line)})
            except json.JSONDecodeError:
              write_record(output, {"type": "operator_parse_error", "raw": line.strip()})
      write_record(output, {"type": "session_end", "ended_unix_ns": time.time_ns()})
  finally:
    if operator_input is not None:
      operator_input.close()
  print(str(args.output))


if __name__ == "__main__":
  main()
