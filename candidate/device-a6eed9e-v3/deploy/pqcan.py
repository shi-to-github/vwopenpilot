def create_steering_control(packer, bus, apply_steer, lkas_enabled):
  values = {
    "LM_Offset": abs(apply_steer),
    "LM_OffSign": 1 if apply_steer < 0 else 0,
    "HCA_Status": 5 if (lkas_enabled and apply_steer != 0) else 3,
    "Vib_Freq": 16,
  }

  return packer.make_can_msg("HCA_1", bus, values)


def create_lka_hud_control(packer, bus, ldw_stock_values, enabled, steering_pressed, hud_alert, hud_control):
  values = ldw_stock_values.copy()

  values.update({
    "LDW_Lampe_gelb": 1 if enabled and steering_pressed else 0,
    "LDW_Lampe_gruen": 1 if enabled and not steering_pressed else 0,
    "LDW_Lernmodus_links": 3 if hud_control.leftLaneDepart else 1 + hud_control.leftLaneVisible,
    "LDW_Lernmodus_rechts": 3 if hud_control.rightLaneDepart else 1 + hud_control.rightLaneVisible,
    "LDW_Textbits": hud_alert,
  })

  return packer.make_can_msg("LDW_Status", bus, values)


def create_acc_buttons_control(packer, bus, gra_stock_values, counter, cancel=False, resume=False, accel=False, decel=False):
  if accel and decel:
    raise ValueError("Only one cruise direction may be requested")
  values = gra_stock_values.copy()

  values.update({
    "COUNTER": counter,
    "GRA_Abbrechen": cancel,
    "GRA_Recall": resume,
  })
  if accel or decel:
    values["GRA_Up_kurz"] = accel
    values["GRA_Down_kurz"] = decel

  return packer.make_can_msg("GRA_Neu", bus, values)


def create_cruise_button_frame(packer, bus, gra_stock_values, counter, direction):
  if direction not in ('up', 'down', 'recall', 'release'):
    raise ValueError('Unknown finite cruise button action')
  values = gra_stock_values.copy()
  for signal in ('GRA_Abbrechen', 'GRA_Neu_Setzen', 'GRA_Recall', 'GRA_Up_kurz',
                 'GRA_Down_kurz', 'GRA_Up_lang', 'GRA_Down_lang', 'GRA_Tip_Up',
                 'GRA_Tip_Down'):
    values[signal] = 0
  values['COUNTER'] = counter
  signal = {'up': 'GRA_Up_kurz', 'down': 'GRA_Down_kurz', 'recall': 'GRA_Recall'}.get(direction)
  if signal:
    values[signal] = 1
  return packer.make_can_msg('GRA_Neu', bus, values)


def acc_control_value(main_switch_on, acc_faulted, long_active):
  if long_active:
    acc_control = 1
  elif main_switch_on:
    acc_control = 2
  else:
    acc_control = 0

  return acc_control


def acc_hud_status_value(main_switch_on, acc_faulted, long_active):
  if acc_faulted:
    hud_status = 6
  elif long_active:
    hud_status = 3
  elif main_switch_on:
    hud_status = 2
  else:
    hud_status = 0

  return hud_status


def create_acc_accel_control(packer, bus, acc_type, enabled, accel, acc_control, stopping, starting, esp_hold):
  commands = []

  values = {
    "ACS_Sta_ADR": acc_control,
    "ACS_StSt_Info": acc_control != 1,
    "ACS_Typ_ACC": acc_type,
    "ACS_Anhaltewunsch": acc_type == 1 and stopping,
    "ACS_Sollbeschl": accel if acc_control == 1 else 3.01,
    "ACS_zul_Regelabw": 0.2 if acc_control == 1 else 1.27,
    "ACS_max_AendGrad": 3.0 if acc_control == 1 else 5.08,
  }

  commands.append(packer.make_can_msg("ACC_System", bus, values))

  return commands


def create_acc_hud_control(packer, bus, acc_hud_status, set_speed, lead_distance):
  values = {
    "ACA_StaACC": acc_hud_status,
    "ACA_Zeitluecke": 2,
    "ACA_V_Wunsch": set_speed,
    "ACA_gemZeitl": lead_distance,
    # TODO: ACA_ID_StaACC, ACA_AnzDisplay, ACA_kmh_mph, ACA_PrioDisp, ACA_Aend_Zeitluecke
    # display/display-prio handling probably needed to stop confusing the instrument cluster
    # kmh_mph handling probably needed to resolve rounding errors in displayed setpoint
  }

  return packer.make_can_msg("ACC_GRA_Anziege", bus, values)
