from cereal import car
from opendbc.can.packer import CANPacker
from common.numpy_fast import clip
from common.conversions import Conversions as CV
from common.realtime import DT_CTRL
from selfdrive.car import apply_std_steer_torque_limits
from selfdrive.car.volkswagen import mqbcan, pqcan
from selfdrive.car.volkswagen.hca_timer_reset import HcaTimerReset, PQ_LONG_STANDBY_ENABLED
from selfdrive.car.volkswagen.pq_stock_cruise_probe import ProbeMode, StockCruiseProbe, consume_command, read_mode
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
    self.pq_hca_timer_reset = HcaTimerReset(100 / self.CCP.HCA_STEP) if CP.carFingerprint in PQ_CARS and PQ_LONG_STANDBY_ENABLED else None
    self.pq_stock_cruise_mode = read_mode() if CP.carFingerprint in PQ_CARS else ProbeMode.v1
    self.pq_stock_cruise_probe = StockCruiseProbe(self.pq_stock_cruise_mode)

  def update(self, CC, CS, ext_bus):
    actuators = CC.actuators
    hud_control = CC.hudControl
    can_sends = []

    # **** Steering Controls ************************************************ #

    if self.frame % self.CCP.HCA_STEP == 0:
      # Logic to avoid HCA state 4 "refused":
      #   * Don't steer unless HCA is in state 3 "ready" or 5 "active"
      #   * Don't steer at standstill
      #   * Don't send > 3.00 Newton-meters torque
      #   * Don't send the same torque for > 6 seconds
      #   * Don't send uninterrupted steering for > 360 seconds
      # One frame of HCA disabled is enough to reset the timer, without zeroing the
      # torque value. Do that anytime we happen to have 0 torque, or failing that,
      # when exceeding ~1/3 the 360 second timer.

      if CC.latActive:
        new_steer = int(round(actuators.steer * self.CCP.STEER_MAX))
        apply_steer = apply_std_steer_torque_limits(new_steer, self.apply_steer_last, CS.out.steeringTorque, self.CCP)
        if apply_steer == 0:
          hcaEnabled = False
          self.hcaEnabledFrameCount = 0
        else:
          self.hcaEnabledFrameCount += 1
          if self.hcaEnabledFrameCount >= 118 * (100 / self.CCP.HCA_STEP):  # 118s
            hcaEnabled = False
            self.hcaEnabledFrameCount = 0
          else:
            hcaEnabled = True
            if self.apply_steer_last == apply_steer:
              self.hcaSameTorqueCount += 1
              if self.hcaSameTorqueCount > 1.9 * (100 / self.CCP.HCA_STEP):  # 1.9s
                apply_steer -= (1, -1)[apply_steer < 0]
                self.hcaSameTorqueCount = 0
            else:
              self.hcaSameTorqueCount = 0
      else:
        hcaEnabled = False
        apply_steer = 0

      if self.pq_hca_timer_reset is not None:
        apply_steer, hcaEnabled, reset_completed = self.pq_hca_timer_reset.update(CC.latActive, apply_steer)
        if not hcaEnabled:
          self.hcaSameTorqueCount = 0
        if reset_completed:
          self.hcaEnabledFrameCount = 0

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

    driver_button_signals = ("GRA_Abbrechen", "GRA_Neu_Setzen", "GRA_Up_lang", "GRA_Down_lang",
                             "GRA_Up_kurz", "GRA_Down_kurz", "GRA_Recall", "GRA_Zeitluecke")
    driver_button_active = self.CP.carFingerprint in PQ_CARS and any(
      CS.gra_stock_values.get(signal, 0) for signal in driver_button_signals)
    if self.CP.carFingerprint in PQ_CARS and self.frame % 10 == 0:
      requested_mode = read_mode()
      if requested_mode != self.pq_stock_cruise_mode:
        previous_probe = self.pq_stock_cruise_probe
        self.pq_stock_cruise_mode = requested_mode
        self.pq_stock_cruise_probe = StockCruiseProbe(requested_mode)
        if previous_probe.engaged and CC.enabled and CS.out.cruiseState.enabled:
          self.pq_stock_cruise_probe.engaged = True
          self.pq_stock_cruise_probe.sent_this_engagement = previous_probe.sent_this_engagement
          self.pq_stock_cruise_probe.faulted = previous_probe.faulted
    probe_command = (consume_command() if self.pq_stock_cruise_mode == ProbeMode.manual_once and
                     self.frame % 100 == 0 else "")
    probe_press = self.pq_stock_cruise_probe.update(
      self.CP.carFingerprint in PQ_CARS and self.CP.pcmCruise and CC.enabled and CS.out.cruiseState.enabled,
      CS.out.cruiseState.speed * CV.MS_TO_KPH, CS.out.vEgo * CV.MS_TO_KPH,
      brake_pressed=CS.out.brakePressed, gas_pressed=CS.out.gasPressed,
      driver_button_active=driver_button_active or CC.cruiseControl.cancel or CC.cruiseControl.resume,
      command=probe_command)
    probe_accel = probe_press and self.pq_stock_cruise_probe.direction == "up"
    probe_decel = probe_press and self.pq_stock_cruise_probe.direction == "down"

    gra_send_ready = self.CP.pcmCruise and CS.gra_stock_values["COUNTER"] != self.gra_acc_counter_last
    if gra_send_ready and (CC.cruiseControl.cancel or CC.cruiseControl.resume or probe_press):
      counter = (CS.gra_stock_values["COUNTER"] + 1) % 16
      if self.CP.carFingerprint in PQ_CARS:
        can_sends.append(self.CCS.create_acc_buttons_control(self.packer_pt, ext_bus, CS.gra_stock_values, counter,
                                                             cancel=CC.cruiseControl.cancel, resume=CC.cruiseControl.resume,
                                                             accel=probe_accel, decel=probe_decel))
        if probe_press:
          self.pq_stock_cruise_probe.mark_sent(CS.out.cruiseState.speed * CV.MS_TO_KPH)
      else:
        can_sends.append(self.CCS.create_acc_buttons_control(self.packer_pt, ext_bus, CS.gra_stock_values, counter,
                                                             cancel=CC.cruiseControl.cancel, resume=CC.cruiseControl.resume))

    new_actuators = actuators.copy()
    new_actuators.steer = self.apply_steer_last / self.CCP.STEER_MAX
    new_actuators.steerOutputCan = self.apply_steer_last

    self.gra_acc_counter_last = CS.gra_stock_values["COUNTER"]
    self.frame += 1
    return new_actuators, can_sends
