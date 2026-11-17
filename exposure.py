"""V45-TL8-M2 physical module: exposure.py. Loaded into the shared runtime namespace.
Do not import directly; use weather_camera.py.
"""


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))

def limited_change(current, requested, maximum_fraction):
    return clamp(requested, current * (1.0 - maximum_fraction), current * (1.0 + maximum_fraction))

def build_camera_controls(mode):
    """Build the libcamera control set for one operating mode.

    DAY returns the automatic profile.  Other modes return manual exposure and
    gain controls while preserving Auto AWB, except NIGHT when learned colour
    gains are available.
    """
    global manual_exposure_us, manual_gain
    if mode == 'DAY':
        return DAY_CAMERA_CONTROLS.copy()
    if manual_exposure_us is None:
        manual_exposure_us = NIGHT_INITIAL_EXPOSURE_US if mode == 'NIGHT' else LOW_LIGHT_INITIAL_EXPOSURE_US
    if manual_gain is None:
        manual_gain = INITIAL_LOW_LIGHT_GAIN
    normal_max_exposure = maximum_exposure_for_mode(mode)
    control_max_exposure = max(normal_max_exposure, int(manual_exposure_us)) if mode_control_pending else normal_max_exposure
    exposure = int(clamp(manual_exposure_us, MIN_EXPOSURE_US, control_max_exposure))
    gain = float(clamp(manual_gain, MIN_ANALOGUE_GAIN, ABSOLUTE_MAX_GAIN))
    frame_duration = max(exposure + 10000, 33333)
    if mode == 'TWILIGHT':
        dynamic_sharpness, dynamic_saturation = (TWILIGHT_SHARPNESS, 1.05)
    elif mode == 'LOW LIGHT':
        dynamic_sharpness, dynamic_saturation = (LOW_LIGHT_SHARPNESS, 1.0)
    else:
        dynamic_sharpness, dynamic_saturation = (NIGHT_SHARPNESS, 1.0)
    camera_controls = {'AeEnable': False, 'ExposureTime': exposure, 'AnalogueGain': gain, 'FrameDurationLimits': (frame_duration, frame_duration), 'AwbEnable': True, 'AwbMode': controls.AwbModeEnum.Auto, 'Brightness': 0.0, 'Contrast': 1.0, 'Saturation': dynamic_saturation, 'Sharpness': dynamic_sharpness}
    if mode == 'NIGHT' and night_colour_gains is not None:
        camera_controls['AwbEnable'] = False
        camera_controls['ColourGains'] = night_colour_gains
    return camera_controls

def update_awb_learning(metadata):
    """Collect stable evening LOW LIGHT Auto-AWB gains for NIGHT locking.

    Samples outside configured gain limits or more than 25 percent from the
    recent median are rejected before entering the rolling history.
    """
    if current_camera_mode != 'LOW LIGHT':
        return
    sunrise, sunset = get_harpenden_sun_times()
    if local_now() < sunrise + (sunset - sunrise) / 2:
        return
    gains = metadata.get('ColourGains')
    if gains is None or len(gains) != 2:
        return
    try:
        red, blue = (float(gains[0]), float(gains[1]))
    except (TypeError, ValueError):
        return
    if not (math.isfinite(red) and math.isfinite(blue)):
        return
    if not (AWB_GAIN_MIN <= red <= AWB_GAIN_MAX and AWB_GAIN_MIN <= blue <= AWB_GAIN_MAX):
        return
    if len(awb_gain_history) >= 5:
        median = np.median(np.asarray(awb_gain_history, dtype=np.float32), axis=0)
        if not (median[0] * (1 - AWB_OUTLIER_FRACTION) <= red <= median[0] * (1 + AWB_OUTLIER_FRACTION) and median[1] * (1 - AWB_OUTLIER_FRACTION) <= blue <= median[1] * (1 + AWB_OUTLIER_FRACTION)):
            return
    awb_gain_history.append((red, blue))

def update_manual_exposure(measurement, metadata):
    """Run one closed-loop manual exposure update.

    The filtered weighted brightness is compared with the active mode target.
    BRIGHTEN increases exposure until the mode limit and then gain. DARKEN
    removes gain first and then shortens exposure. Highlight protection takes
    precedence over the normal brightness target.

    Detailed diagnostics are intentionally retained here because dawn/dusk
    tuning depends on comparing requested versus sensor-applied settings,
    metering regions, smoothing, controller limiting and oscillation history.
    """
    global manual_exposure_us, manual_gain, filtered_brightness
    global current_exposure_action, last_actual_exposure, last_actual_gain
    global pending_control_captures, mode_control_pending
    global mode_transition_target_exposure_us
    global low_light_entry_floor_product
    global low_light_floor_interventions
    if current_camera_mode not in ('TWILIGHT', 'LOW LIGHT', 'NIGHT'):
        return
    actual_exposure = int(metadata.get('ExposureTime', manual_exposure_us or NIGHT_INITIAL_EXPOSURE_US))
    actual_gain = float(metadata.get('AnalogueGain', manual_gain or INITIAL_LOW_LIGHT_GAIN))
    digital_gain = float(metadata.get('DigitalGain', 1.0))
    if last_actual_exposure is not None:
        exposure_ratio = max(actual_exposure / max(last_actual_exposure, 1), last_actual_exposure / max(actual_exposure, 1))
        if exposure_ratio > 1.5:
            logger.warning('[EXPOSURE JUMP] %dus -> %dus (x%.2f)', last_actual_exposure, actual_exposure, exposure_ratio)
    last_actual_exposure = actual_exposure
    last_actual_gain = actual_gain
    requested_before_capture_exposure = manual_exposure_us
    requested_before_capture_gain = manual_gain
    exp_error = actual_exposure - int(requested_before_capture_exposure or 0)
    gain_error = actual_gain - float(requested_before_capture_gain or 0.0)
    logger.info('[LAG] RequestedExp=%s ActualExp=%d DeltaExp=%+d RequestedGain=%.2f ActualGain=%.2f DeltaGain=%+.2f', requested_before_capture_exposure, actual_exposure, exp_error, float(requested_before_capture_gain or 0.0), actual_gain, gain_error)
    logger.info('[META] ActExp=%dus (%.0fms) ActGain=%.2f DigitalGain=%.2f ColourGains=%s', actual_exposure, actual_exposure / 1000.0, actual_gain, digital_gain, metadata.get('ColourGains'))
    if manual_exposure_us is None:
        manual_exposure_us = actual_exposure
    if manual_gain is None:
        manual_gain = actual_gain
    controller_exposure = int(manual_exposure_us)
    controller_gain = float(manual_gain)

    exposure_acknowledged = abs(actual_exposure - controller_exposure) <= CONTROL_ACK_EXPOSURE_TOLERANCE_US
    gain_acknowledged = abs(actual_gain - controller_gain) <= CONTROL_ACK_GAIN_TOLERANCE
    control_acknowledged = exposure_acknowledged and gain_acknowledged
    waiting_for_camera = False
    ack_timed_out = False
    if control_acknowledged:
        pending_control_captures = 0
    else:
        pending_control_captures += 1
        if pending_control_captures < CONTROL_ACK_MAX_CAPTURES:
            waiting_for_camera = True
            logger.info(
                '[CONTROL ACK] WAITING | Capture=%d/%d | Requested=%.0fms G%.2f | Actual=%.0fms G%.2f',
                pending_control_captures,
                CONTROL_ACK_MAX_CAPTURES,
                controller_exposure / 1000.0,
                controller_gain,
                actual_exposure / 1000.0,
                actual_gain,
            )
        else:
            logger.warning(
                '[CONTROL ACK] TIMEOUT | Captures=%d | Requested=%.0fms G%.2f | Actual=%.0fms G%.2f | Reconciling',
                pending_control_captures,
                controller_exposure / 1000.0,
                controller_gain,
                actual_exposure / 1000.0,
                actual_gain,
            )
            controller_exposure = actual_exposure
            controller_gain = actual_gain
            manual_exposure_us = actual_exposure
            manual_gain = actual_gain
            pending_control_captures = 0
            ack_timed_out = True
            audit_event(
                'camera_control_ack_timeout',
                severity='WARNING',
                requested_exposure_us=requested_before_capture_exposure,
                requested_gain=requested_before_capture_gain,
                actual_exposure_us=actual_exposure,
                actual_gain=round(actual_gain, 3),
            )

    if current_camera_mode == 'NIGHT':
        target_low, target_high = (NIGHT_TARGET_LOW, NIGHT_TARGET_HIGH)
        deadband = NIGHT_BRIGHTNESS_DEADBAND
    elif current_camera_mode == 'LOW LIGHT':
        target_low, target_high = (LOW_LIGHT_TARGET_LOW, LOW_LIGHT_TARGET_HIGH)
        deadband = LOW_LIGHT_BRIGHTNESS_DEADBAND
    else:
        target_low, target_high = (TWILIGHT_TARGET_LOW, TWILIGHT_TARGET_HIGH)
        deadband = TWILIGHT_BRIGHTNESS_DEADBAND
    raw_brightness = measurement['brightness']
    logger.info('[METER] Sky=%.1f Horizon=%.1f Foreground=%.1f Raw=%.1f Contrast=%.1f Highlights=%.2f%%', measurement['sky'], measurement['horizon'], measurement['foreground'], raw_brightness, measurement['contrast'], measurement['highlights'])
    if mode_control_pending and control_acknowledged and mode_transition_target_exposure_us is None:
        filtered_brightness = raw_brightness
        mode_control_pending = False
        logger.info('[MODE CONTROL] ACKNOWLEDGED | Mode=%s | Filter reset to %.1f', current_camera_mode, raw_brightness)
    if filtered_brightness is None:
        filtered_brightness = raw_brightness
        previous_filtered = None
    else:
        previous_filtered = filtered_brightness
        filtered_brightness = (1.0 - BRIGHTNESS_FILTER_ALPHA) * filtered_brightness + BRIGHTNESS_FILTER_ALPHA * raw_brightness
    if previous_filtered is not None:
        logger.debug('[FILTER] Raw=%.1f Prev=%.1f New=%.1f Alpha=%.2f', raw_brightness, previous_filtered, filtered_brightness, BRIGHTNESS_FILTER_ALPHA)
    brightness = filtered_brightness
    logger.debug('[DEADBAND] Mode=%s Deadband=%.1f Brighten<%.1f Darken>%.1f', current_camera_mode, deadband, target_low - deadband, target_high + deadband)
    measurement.update({'filtered_brightness': brightness, 'target_low': target_low, 'target_high': target_high, 'brightness_deadband': deadband})
    highlights = measurement['highlights']
    max_highlights = NIGHT_MAX_HIGHLIGHT_PERCENT if current_camera_mode == 'NIGHT' else LOW_LIGHT_MAX_HIGHLIGHT_PERCENT
    normal_max_exposure = maximum_exposure_for_mode(current_camera_mode)
    max_exposure = max(normal_max_exposure, controller_exposure) if mode_transition_target_exposure_us is not None else normal_max_exposure
    requested_exposure = controller_exposure
    requested_gain = controller_gain
    action = 'HOLD'
    at_exposure_limit = actual_exposure >= max_exposure - 50000
    at_gain_limit = actual_gain >= ABSOLUTE_MAX_GAIN - 0.01
    if waiting_for_camera:
        action = 'WAITING FOR CAMERA'
    elif ack_timed_out:
        action = 'ACK TIMEOUT'
    elif mode_transition_target_exposure_us is not None:
        if controller_exposure > mode_transition_target_exposure_us + CONTROL_ACK_EXPOSURE_TOLERANCE_US:
            action = 'MODE TRANSITION'
            requested_exposure = max(
                mode_transition_target_exposure_us,
                controller_exposure * (1.0 - MODE_TRANSITION_MAX_EXPOSURE_CHANGE_FRACTION),
            )
        else:
            mode_transition_target_exposure_us = None
            mode_control_pending = False
            filtered_brightness = raw_brightness
            brightness = raw_brightness
            measurement['filtered_brightness'] = brightness
            action = 'HOLD'
            logger.info('[MODE RAMP] COMPLETE | Mode=%s | Exp=%.0fms | Filter reset to %.1f', current_camera_mode, controller_exposure / 1000.0, raw_brightness)
    elif mode_control_pending:
        action = 'MODE SETTLING'
    elif brightness < target_low and at_exposure_limit and at_gain_limit:
        action = 'LIMIT REACHED'
        if current_exposure_action != 'LIMIT REACHED':
            logger.info('[LIMIT REACHED] Brightness %.1f below target %.1f | Exposure %.0fms | Gain %.2f | No further increase possible', brightness, target_low, actual_exposure / 1000.0, actual_gain)
    elif highlights > max_highlights:
        action = 'HIGHLIGHT PROTECTION'
        if actual_gain > MIN_ANALOGUE_GAIN:
            requested_gain = controller_gain * 0.9
        else:
            requested_exposure = controller_exposure * 0.85
    elif brightness < target_low - deadband:
        action = 'BRIGHTEN'
        ratio = clamp((target_low + target_high) / 2.0 / max(brightness, 5.0), 1.0, 1.3)
        if not at_exposure_limit:
            requested_exposure = min(max_exposure, controller_exposure * ratio)
        else:
            logger.info('[SATURATION] Exposure limit reached %.0fms, switching to gain control', actual_exposure / 1000.0)
            requested_gain = min(ABSOLUTE_MAX_GAIN, controller_gain * min(ratio, 1.2))
    elif brightness > target_high + deadband:
        action = 'DARKEN'
        ratio = clamp((target_low + target_high) / 2.0 / brightness, 0.7, 1.0)
        gain_effectively_minimum = controller_gain <= MIN_ANALOGUE_GAIN + CONTROL_ACK_GAIN_TOLERANCE
        if not gain_effectively_minimum:
            requested_gain = max(MIN_ANALOGUE_GAIN, controller_gain * ratio)
        else:
            requested_gain = MIN_ANALOGUE_GAIN
            requested_exposure = max(MIN_EXPOSURE_US, controller_exposure * ratio)
    logger.debug('[EXPOSURE DECISION] Mode=%s Bright=%.1f Target=%.1f-%.1f Exp=%d MaxExp=%d ReqExp=%.0f ReqGain=%.2f', current_camera_mode, brightness, target_low, target_high, actual_exposure, max_exposure, requested_exposure, requested_gain)
    logger.debug('[CTRL RAW] Action=%s Bright=%.1f TargetLow=%.1f TargetHigh=%.1f ReqExp=%.0f ReqGain=%.2f', action, brightness, target_low, target_high, requested_exposure, requested_gain)
    pre_limit_exposure = requested_exposure
    pre_limit_gain = requested_gain
    exposure_change_fraction = MODE_TRANSITION_MAX_EXPOSURE_CHANGE_FRACTION if action == 'MODE TRANSITION' else MAX_EXPOSURE_CHANGE_FRACTION
    requested_exposure = limited_change(controller_exposure, requested_exposure, exposure_change_fraction)
    requested_gain = limited_change(controller_gain, requested_gain, MAX_GAIN_CHANGE_FRACTION)
    if pre_limit_exposure != requested_exposure or abs(pre_limit_gain - requested_gain) > 0.001:
        logger.info('[CTRL LIMITED] Exp %.0f -> %.0f Gain %.2f -> %.2f', pre_limit_exposure, requested_exposure, pre_limit_gain, requested_gain)
    if (
        current_camera_mode == 'LOW LIGHT'
        and low_light_entry_floor_product is not None
        and action != 'HIGHLIGHT PROTECTION'
    ):
        requested_product = float(requested_exposure) * float(requested_gain)
        if requested_product < low_light_entry_floor_product:
            floor_exposure = low_light_entry_floor_product / max(float(requested_gain), MIN_ANALOGUE_GAIN)
            floor_exposure = clamp(floor_exposure, MIN_EXPOSURE_US, max_exposure)
            if floor_exposure * requested_gain < low_light_entry_floor_product:
                requested_gain = clamp(
                    low_light_entry_floor_product / max(float(floor_exposure), 1.0),
                    MIN_ANALOGUE_GAIN,
                    ABSOLUTE_MAX_GAIN,
                )
            low_light_floor_interventions += 1
            
            logger.info(
                '[LOW LIGHT FLOOR] Applied | Requested=%.1fms-eq | Floor=%.1fms-eq | Result=%.0fms G%.2f',
                requested_product / 1000.0,
                low_light_entry_floor_product / 1000.0,
                floor_exposure / 1000.0,
                requested_gain,
            )
            requested_exposure = floor_exposure
    manual_exposure_us = int(clamp(requested_exposure, MIN_EXPOSURE_US, max_exposure))
    manual_gain = float(clamp(requested_gain, MIN_ANALOGUE_GAIN, ABSOLUTE_MAX_GAIN))
    exposure_changed = abs(manual_exposure_us - controller_exposure) >= CONTROL_SUBMIT_EXPOSURE_THRESHOLD_US
    gain_changed = abs(manual_gain - controller_gain) >= CONTROL_SUBMIT_GAIN_THRESHOLD
    if (exposure_changed or gain_changed) and not ack_timed_out:
        frame_duration = max(manual_exposure_us + 10000, 33333)
        with camera_lock:
            picam2.set_controls({
                'ExposureTime': manual_exposure_us,
                'AnalogueGain': manual_gain,
                'FrameDurationLimits': (frame_duration, frame_duration),
            })
        pending_control_captures = 0
        logger.info(
            '[CONTROL SUBMIT] Exp=%.0fms G%.2f | ChangedExp=%s ChangedGain=%s',
            manual_exposure_us / 1000.0,
            manual_gain,
            exposure_changed,
            gain_changed,
        )
    current_exposure_action = action
    exposure_action_history.append(action)
    recent_actions = list(exposure_action_history)
    if len(recent_actions) >= 6:
        alternating_patterns = [['BRIGHTEN', 'DARKEN', 'BRIGHTEN', 'DARKEN', 'BRIGHTEN', 'DARKEN'], ['DARKEN', 'BRIGHTEN', 'DARKEN', 'BRIGHTEN', 'DARKEN', 'BRIGHTEN']]
        next_boundary = None
        if current_camera_mode == 'NIGHT':
            next_boundary = LOW_LIGHT_ELEVATION
        elif current_camera_mode == 'LOW LIGHT':
            next_boundary = NIGHT_ELEVATION
        elif current_camera_mode == 'TWILIGHT':
            next_boundary = DAY_ELEVATION
        delta_to_boundary = abs(next_boundary - current_solar_elevation) if next_boundary is not None else 0.0
        if recent_actions[-6:] in alternating_patterns:
            logger.warning('[OSCILLATION] Exposure controller alternating | Mode=%s | Sun=%.2f | DeltaSun=%.2f | Brightness=%.1f | Exp=%d | Gain=%.2f | History=%s', current_camera_mode, current_solar_elevation, delta_to_boundary, brightness, actual_exposure, actual_gain, recent_actions[-6:])
            audit_event('exposure_oscillation', severity='WARNING', mode=current_camera_mode, solar_elevation=round(current_solar_elevation, 2), brightness=round(brightness, 1), exposure_us=actual_exposure, gain=round(actual_gain, 2))
    logger.info('[EXPOSURE] %s | Raw %.1f | Filtered %.1f | Actual %.0fms G%.2f DG%.2f | ReqPreLimit Exp %.0fms G%.2f | ReqPostLimit Exp %.0fms G%.2f | Next %.0fms G%.2f | Highlights %.2f%%', action, raw_brightness, brightness, actual_exposure / 1000.0, actual_gain, digital_gain, pre_limit_exposure / 1000.0, pre_limit_gain, requested_exposure / 1000.0, requested_gain, manual_exposure_us / 1000.0, manual_gain, highlights)
