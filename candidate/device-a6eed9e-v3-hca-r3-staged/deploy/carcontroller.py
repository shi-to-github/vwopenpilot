from cereal import car
from opendbc.can.packer import CANPacker
from common.numpy_fast import clip
from common.conversions import Conversions as CV
from common.realtime import DT_CTRL
from selfdrive.car import apply_std_steer_torque_limits
from selfdrive.car.volkswagen import mqbcan, pqcan
from selfdrive.car.volkswagen.hca_timer_reset import HcaTimerReset
from selfdrive.car.volkswagen.pq46_cruise import CruiseTrim
from selfdrive.car.volkswagen.pq46_runtime import Runtime
from selfdrive.car.volkswagen.values import CANBUS, PQ_CARS, CarControllerParams

VisualAlert = car.CarControl.HUDControl.VisualAlert
LongCtrlState = car.CarControl.Actuators.LongControlState


class CarController:
  def __init__(self, dbc_name, CP, VM):
    self.CP = CP
    self.CCP = CarControllerParams(CP)
    self.CCS = pqcan if CP.carFingerprint in PQ_CARS else mqbcan
    self.packer_pt = CANPacker(dbc_name)

    self.apply_steer_last = 0
    self.gra_acc_counter_last = None
    self.frame = 0
    self.hcaSameTorqueCount = 0
    self.hcaEnabledFrameCount = 0
    self.pq_hca_timer_reset = HcaTimerReset(100 / self.CCP.HCA_STEP, steer_max=self.CCP.STEER_MAX) if CP.carFingerprint in PQ_CARS else None
    self.pq_runtime = Runtime() if CP.carFingerprint in PQ_CARS else None
    self.pq_cruise = CruiseTrim()

  def update(self, CC, CS, ext_bus):
    actuators = CC.actuators
    hud_control = CC.hudControl
    can_sends = []
    remaining = (max(0, self.pq_hca_timer_reset.required - self.pq_hca_timer_reset.standby) /
                 self.pq_hca_timer_reset.hz) if self.pq_hca_timer_reset is not None and self.pq_hca_timer_reset.standby else (self.pq_hca_timer_reset.required /
                 self.pq_hca_timer_reset.hz if self.pq_hca_timer_reset is not None else 2)
    notice_delay = (self.pq_hca_timer_reset.notice_remaining_s()
                    if self.pq_hca_timer_reset is not None and self.pq_hca_timer_reset.notice_id else 3)
    notice_id = self.pq_hca_timer_reset.notice_id if self.pq_hca_timer_reset is not None else ''
    now = self.pq_runtime.update(CS.out.vEgo, remaining, notice_delay, notice_id) if self.pq_runtime is not None else 0

    # **** Steering Controls ************************************************ #

    if self.frame % self.CCP.HCA_STEP == 0:
      raw_steer = int(round(actuators.steer * self.CCP.STEER_MAX)) if CC.latActive else 0
      # Keep baseline non-PQ behavior. The PQ state machine overrides only its
      # HCA enabled/torque outputs after the normal driver/rate/torque limits.
      if CC.latActive:
        apply_steer = apply_std_steer_torque_limits(raw_steer, self.apply_steer_last, CS.out.steeringTorque, self.CCP)
        if apply_steer == 0:
          hcaEnabled = False
          self.hcaEnabledFrameCount = 0
        else:
          self.hcaEnabledFrameCount += 1
          if self.hcaEnabledFrameCount >= 118 * (100 / self.CCP.HCA_STEP):
            hcaEnabled = False
            self.hcaEnabledFrameCount = 0
          else:
            hcaEnabled = True
            if self.apply_steer_last == apply_steer:
              self.hcaSameTorqueCount += 1
              if self.hcaSameTorqueCount > 1.9 * (100 / self.CCP.HCA_STEP):
                apply_steer -= (1, -1)[apply_steer < 0]
                self.hcaSameTorqueCount = 0
            else:
              self.hcaSameTorqueCount = 0
      else:
        hcaEnabled = False
        apply_steer = 0
      if self.pq_hca_timer_reset is not None:
        quiet = self.pq_runtime.window_ok and self.pq_cruise.pulse.phase not in ('press', 'release', 'wait')
        inputs = [('driver_steering', CS.out.steeringPressed), ('left_blinker', CS.out.leftBlinker),
                  ('right_blinker', CS.out.rightBlinker), ('brake', CS.out.brakePressed), ('gas', CS.out.gasPressed),
                  ('can_invalid', not CS.out.canValid)]
        input_reason = next((name for name, active in inputs if active), '')
        driver_input = bool(input_reason)
        apply_steer, hcaEnabled, _ = self.pq_hca_timer_reset.update(
          CC.latActive, apply_steer, raw_torque=raw_steer,
          window_ok=quiet, driver_input=driver_input,
          continue_ok=self.pq_runtime.continue_ok, window_reason=self.pq_runtime.window_reason if not self.pq_runtime.window_ok else 'cruise_pulse',
          continue_reason=self.pq_runtime.continue_reason, input_reason=input_reason,
          delayed_ok=self.pq_runtime.delayed_ok and self.pq_cruise.pulse.phase not in ('press', 'release', 'wait'),
          delayed_reason=self.pq_runtime.delayed_reason, notice_ack=self.pq_runtime.notice_ack,
          notice_ready=self.pq_runtime.notice_ready, now=now)
        if not hcaEnabled:
          self.hcaSameTorqueCount = 0

      self.apply_steer_last = apply_steer
      can_sends.append(self.CCS.create_steering_control(self.packer_pt, CANBUS.pt, apply_steer, hcaEnabled))

    # **** Acceleration Controls ******************************************** #

    if self.frame % self.CCP.ACC_CONTROL_STEP == 0 and self.CP.openpilotLongitudinalControl:
      acc_control = self.CCS.acc_control_value(CS.out.cruiseState.available, CS.out.accFaulted, CC.longActive)
      accel = clip(actuators.accel, self.CCP.ACCEL_MIN, self.CCP.ACCEL_MAX) if CC.longActive else 0
      stopping = actuators.longControlState == LongCtrlState.stopping
      starting = actuators.longControlState == LongCtrlState.starting
      can_sends.extend(self.CCS.create_acc_accel_control(self.packer_pt, CANBUS.pt, CS.acc_type, CC.longActive, accel,
                                                         acc_control, stopping, starting, CS.esp_hold_confirmation))

    # **** HUD Controls ***************************************************** #

    if self.frame % self.CCP.LDW_STEP == 0:
      hud_alert = 0
      if hud_control.visualAlert in (VisualAlert.steerRequired, VisualAlert.ldw):
        hud_alert = self.CCP.LDW_MESSAGES["laneAssistTakeOver"]
      can_sends.append(self.CCS.create_lka_hud_control(self.packer_pt, CANBUS.pt, CS.ldw_stock_values, CC.enabled,
                                                       CS.out.steeringPressed, hud_alert, hud_control))

    if self.frame % self.CCP.ACC_HUD_STEP == 0 and self.CP.openpilotLongitudinalControl:
      lead_distance = 0
      if hud_control.leadVisible and self.frame * DT_CTRL > 1.0:  # Don't display lead until we know the scaling factor
        lead_distance = 512 if CS.upscale_lead_car_signal else 8
      acc_hud_status = self.CCS.acc_hud_status_value(CS.out.cruiseState.available, CS.out.accFaulted, CC.longActive)
      set_speed = hud_control.setSpeed * CV.MS_TO_KPH  # FIXME: follow the recent displayed-speed updates, also use mph_kmh toggle to fix display rounding problem?
      can_sends.append(self.CCS.create_acc_hud_control(self.packer_pt, CANBUS.pt, acc_hud_status, set_speed,
                                                       lead_distance))

    # **** Stock ACC Button Controls **************************************** #

    driver_button_signals = ('GRA_Abbrechen', 'GRA_Neu_Setzen', 'GRA_Up_lang', 'GRA_Down_lang',
                             'GRA_Up_kurz', 'GRA_Down_kurz', 'GRA_Recall', 'GRA_Zeitluecke')
    is_pq = self.CP.carFingerprint in PQ_CARS
    driver_button = is_pq and any(CS.gra_stock_values.get(s, 0) for s in driver_button_signals)
    if is_pq:
      self.pq_cruise.set_mode(self.pq_runtime.mode)
      self.pq_cruise.update(
        now, self.CP.pcmCruise and CC.enabled and CS.out.cruiseState.enabled,
        getattr(CS, 'pq_motor_target_kph', 0), CS.out.vEgo * CV.MS_TO_KPH,
        feedback_fresh=getattr(CS, 'pq_motor_target_fresh', False),
        can_valid=CS.out.canValid and getattr(CS, 'pq_gra_fresh', False),
        driver_button=driver_button or CC.cruiseControl.cancel or CC.cruiseControl.resume,
        brake=CS.out.brakePressed, gas=CS.out.gasPressed,
        data_fresh=self.pq_runtime.lead_fresh, lead=self.pq_runtime.lead,
        steer_reset=bool(self.pq_hca_timer_reset.standby))

    counter_changed = CS.gra_stock_values['COUNTER'] != self.gra_acc_counter_last
    if self.CP.pcmCruise and counter_changed:
      self.gra_acc_counter_last = CS.gra_stock_values['COUNTER']
      counter = (self.gra_acc_counter_last + 1) % 16
      if CC.cruiseControl.cancel or CC.cruiseControl.resume:
        can_sends.append(self.CCS.create_acc_buttons_control(
          self.packer_pt, ext_bus, CS.gra_stock_values, counter,
          cancel=CC.cruiseControl.cancel, resume=CC.cruiseControl.resume))
      elif (is_pq and CC.enabled and CS.out.cruiseState.enabled and CS.out.canValid and
            CS.pq_motor_target_fresh and CS.pq_gra_fresh and not driver_button and
            not CS.out.brakePressed and not CS.out.gasPressed and CS.out.vEgo * CV.MS_TO_KPH >= 70):
        action = self.pq_cruise.pulse.frame(now)
        if action:
          can_sends.append(self.CCS.create_cruise_button_frame(
            self.packer_pt, ext_bus, CS.gra_stock_values, counter, action))
    if is_pq:
      self.pq_runtime.write_status(now, self.pq_hca_timer_reset, self.pq_cruise, CS)

    new_actuators = actuators.copy()
    new_actuators.steer = self.apply_steer_last / self.CCP.STEER_MAX
    new_actuators.steerOutputCan = self.apply_steer_last

    self.gra_acc_counter_last = CS.gra_stock_values["COUNTER"]
    self.frame += 1
    return new_actuators, can_sends
