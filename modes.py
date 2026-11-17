"""Physical runtime module: modes.py. Loaded into the shared runtime namespace.
Do not import directly; use weather_camera.py.
"""

def local_now():
    return datetime.now(HARPENDEN_TIMEZONE)

def calculate_sun_time(date_value, latitude, longitude, sunrise=True):
    zenith = 90.833
    day_of_year = date_value.timetuple().tm_yday
    longitude_hour = longitude / 15.0
    approximate_time = day_of_year + ((6 if sunrise else 18) - longitude_hour) / 24
    mean_anomaly = 0.9856 * approximate_time - 3.289
    true_longitude = (mean_anomaly + 1.916 * math.sin(math.radians(mean_anomaly)) + 0.02 * math.sin(math.radians(2 * mean_anomaly)) + 282.634) % 360
    right_ascension = math.degrees(math.atan(0.91764 * math.tan(math.radians(true_longitude)))) % 360
    right_ascension += math.floor(true_longitude / 90) * 90 - math.floor(right_ascension / 90) * 90
    right_ascension /= 15
    sin_declination = 0.39782 * math.sin(math.radians(true_longitude))
    cos_declination = math.cos(math.asin(sin_declination))
    cos_hour_angle = (math.cos(math.radians(zenith)) - sin_declination * math.sin(math.radians(latitude))) / (cos_declination * math.cos(math.radians(latitude)))
    cos_hour_angle = clamp(cos_hour_angle, -1.0, 1.0)
    hour_angle = 360 - math.degrees(math.acos(cos_hour_angle)) if sunrise else math.degrees(math.acos(cos_hour_angle))
    hour_angle /= 15
    local_mean_time = hour_angle + right_ascension - 0.06571 * approximate_time - 6.622
    utc_hour = (local_mean_time - longitude_hour) % 24
    hours = int(utc_hour)
    minutes_float = (utc_hour - hours) * 60
    minutes = int(minutes_float)
    seconds = int(round((minutes_float - minutes) * 60))
    if seconds >= 60:
        seconds = 0
        minutes += 1
    if minutes >= 60:
        minutes = 0
        hours += 1
    if hours >= 24:
        hours = 0
        date_value += timedelta(days=1)
    utc_datetime = datetime(date_value.year, date_value.month, date_value.day, hours, minutes, seconds, tzinfo=UTC_TIMEZONE)
    return utc_datetime.astimezone(HARPENDEN_TIMEZONE)

def get_harpenden_sun_times():
    global cached_sun_date, cached_sunrise, cached_sunset
    today = local_now().date()
    if cached_sun_date != today:
        cached_sunrise = calculate_sun_time(today, HARPENDEN_LATITUDE, HARPENDEN_LONGITUDE, True)
        cached_sunset = calculate_sun_time(today, HARPENDEN_LATITUDE, HARPENDEN_LONGITUDE, False)
        cached_sun_date = today
        logger.info('[SUN EVENTS] Sunrise %s | Sunset %s', cached_sunrise.strftime('%H:%M:%S'), cached_sunset.strftime('%H:%M:%S'))
    return (cached_sunrise, cached_sunset)

def calculate_solar_elevation(current_time):
    utc_time = current_time.astimezone(UTC_TIMEZONE)
    day_of_year = utc_time.timetuple().tm_yday
    decimal_hour = utc_time.hour + utc_time.minute / 60.0 + utc_time.second / 3600.0
    gamma = 2.0 * math.pi / 365.0 * (day_of_year - 1 + (decimal_hour - 12) / 24.0)
    equation_of_time = 229.18 * (7.5e-05 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma) - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    declination = 0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma)
    true_solar_minutes = (decimal_hour * 60.0 + equation_of_time + 4.0 * HARPENDEN_LONGITUDE) % 1440.0
    hour_angle = true_solar_minutes / 4.0 - 180.0
    latitude_radians = math.radians(HARPENDEN_LATITUDE)
    cosine_zenith = math.sin(latitude_radians) * math.sin(declination) + math.cos(latitude_radians) * math.cos(declination) * math.cos(math.radians(hour_angle))
    return 90.0 - math.degrees(math.acos(clamp(cosine_zenith, -1.0, 1.0)))

def determine_camera_mode():
    """Return the solar-elevation mode, applying hysteresis around boundaries.

    Hysteresis uses different transition elevations depending on direction of
    travel.  This prevents rapid mode chatter due to tiny solar-elevation or
    timing changes near a threshold.
    """
    global current_solar_elevation
    elevation = calculate_solar_elevation(local_now())
    current_solar_elevation = elevation
    boundaries = [NIGHT_ELEVATION, LOW_LIGHT_ELEVATION, DAY_ELEVATION]
    modes = ['NIGHT', 'LOW LIGHT', 'TWILIGHT', 'DAY']
    if current_camera_mode is None:
        return modes[sum((elevation >= boundary for boundary in boundaries))]
    try:
        stage = modes.index(current_camera_mode)
    except ValueError:
        stage = sum((elevation >= boundary for boundary in boundaries))
    while stage < 3 and elevation >= boundaries[stage] + SOLAR_MODE_HYSTERESIS_DEGREES:
        stage += 1
    while stage > 0 and elevation < boundaries[stage - 1] - SOLAR_MODE_HYSTERESIS_DEGREES:
        stage -= 1
    return modes[stage]

def maximum_exposure_for_mode(mode):
    """Return the longest permitted manual exposure for the requested mode."""
    if mode == 'TWILIGHT':
        return MAX_TWILIGHT_EXPOSURE_US
    if mode == 'LOW LIGHT':
        return MAX_LOW_LIGHT_EXPOSURE_US
    return MAX_NIGHT_EXPOSURE_US

def configure_camera_mode(force=False):
    """Transition to the required solar mode and apply its camera controls.

    Dawn preserves manual state from LOW LIGHT into TWILIGHT.  Dusk samples the
    current DAY AE metadata before switching TWILIGHT to manual control.  When
    force=True the active controls are reapplied even if the mode did not
    change, which is required after camera recovery.
    """
    global current_camera_mode, manual_exposure_us, manual_gain
    global night_colour_gains, filtered_brightness, pending_control_captures
    global mode_control_pending, mode_transition_target_exposure_us
    global low_light_entry_floor_product
    global mode_entered_time
    global mode_transition_count
    global mode_last_duration_seconds
    
    required_mode = determine_camera_mode()
    if not force and required_mode == current_camera_mode:
        return False
    
    if current_camera_mode is None and mode_entered_time is None:
        mode_entered_time = local_now()

    previous_mode = current_camera_mode
    mode_changed = required_mode != previous_mode
    if mode_changed:
        transition_duration = None

        if mode_entered_time is not None:
            transition_duration = (
                local_now() - mode_entered_time
            ).total_seconds()

        mode_last_duration_seconds = transition_duration
        mode_transition_count += 1
        arm_mode_validation(previous_mode, required_mode, float(filtered_brightness or 0.0), 0.0, int(manual_exposure_us or 0), float(manual_gain or 0.0))
        mode_entered_time = local_now()

        logger.info(
            '[MODE TRANSITION] %s -> %s | Duration=%s sec | Sun=%.2f',
            previous_mode or 'START',
            required_mode,
            round(transition_duration, 1)
            if transition_duration is not None else '--',
            current_solar_elevation,
        )
        pending_control_captures = 0
        mode_control_pending = required_mode in ('TWILIGHT', 'LOW LIGHT', 'NIGHT')
        mode_transition_target_exposure_us = None
        if required_mode != 'LOW LIGHT':
            low_light_entry_floor_product = None
        logger.info('[MODE DEBUG] %s -> %s | Exp=%s | Gain=%s | Filtered=%s | Sun=%.2f', previous_mode, required_mode, manual_exposure_us, manual_gain, filtered_brightness, current_solar_elevation)
        if previous_mode == 'DAY' and required_mode == 'TWILIGHT' or (previous_mode == 'LOW LIGHT' and required_mode == 'NIGHT') or (previous_mode == 'NIGHT' and required_mode == 'LOW LIGHT'):
            filtered_brightness = None
        exposure_action_history.clear()
        sunrise, sunset = get_harpenden_sun_times()
        evening = local_now() >= sunrise + (sunset - sunrise) / 2
        if required_mode == 'TWILIGHT' and evening:
            night_colour_gains = None
            awb_gain_history.clear()
            logger.info('[AWB] Evening learning window reset')
        if required_mode == 'LOW LIGHT':
            with camera_lock:
                metadata = picam2.capture_metadata()
            if manual_exposure_us is None or previous_mode == 'DAY':
                manual_exposure_us = int(metadata.get('ExposureTime', LOW_LIGHT_INITIAL_EXPOSURE_US))
            if manual_gain is None or previous_mode == 'DAY':
                manual_gain = float(metadata.get('AnalogueGain', INITIAL_LOW_LIGHT_GAIN))
            if previous_mode == 'NIGHT' and manual_exposure_us > MAX_LOW_LIGHT_EXPOSURE_US:
                inherited_exposure = int(manual_exposure_us)
                mode_transition_target_exposure_us = MAX_LOW_LIGHT_EXPOSURE_US
                manual_exposure_us = int(max(
                    MAX_LOW_LIGHT_EXPOSURE_US,
                    inherited_exposure * (1.0 - MODE_TRANSITION_MAX_EXPOSURE_CHANGE_FRACTION),
                ))
                logger.info(
                    '[MODE RAMP] NIGHT -> LOW LIGHT | Inherited=%dms | First=%dms | Target=%dms',
                    inherited_exposure // 1000,
                    manual_exposure_us // 1000,
                    MAX_LOW_LIGHT_EXPOSURE_US // 1000,
                )
            if previous_mode == 'TWILIGHT':
                low_light_entry_floor_product = float(manual_exposure_us) * float(manual_gain)
                logger.info(
                    '[LOW LIGHT ENTRY FLOOR] Armed | Exp=%dus | Gain=%.2f | Floor=%.1fms-eq',
                    manual_exposure_us, manual_gain, low_light_entry_floor_product / 1000.0,
                )
            else:
                low_light_entry_floor_product = None
            logger.info('[LOW LIGHT ENTRY] Exp=%dus Gain=%.2f', manual_exposure_us, manual_gain)
        elif required_mode == 'NIGHT':
            if len(awb_gain_history) >= AWB_MINIMUM_SAMPLES:
                gains = np.median(np.asarray(awb_gain_history, dtype=np.float32), axis=0)
                night_colour_gains = (float(clamp(gains[0], AWB_GAIN_MIN, AWB_GAIN_MAX)), float(clamp(gains[1], AWB_GAIN_MIN, AWB_GAIN_MAX)))
                logger.info('[AWB] Locked NIGHT gains R %.3f | B %.3f from %d samples', night_colour_gains[0], night_colour_gains[1], len(awb_gain_history))
                audit_event('night_awb_locked', red_gain=round(night_colour_gains[0], 3), blue_gain=round(night_colour_gains[1], 3), sample_count=len(awb_gain_history))
            else:
                night_colour_gains = None
                logger.warning('[AWB] Only %d samples; NIGHT will continue Auto AWB', len(awb_gain_history))
        elif required_mode == 'TWILIGHT':
            if previous_mode == 'DAY':
                with camera_lock:
                    metadata = picam2.capture_metadata()
                manual_exposure_us = int(metadata.get('ExposureTime', LOW_LIGHT_INITIAL_EXPOSURE_US))
                manual_gain = float(metadata.get('AnalogueGain', MIN_ANALOGUE_GAIN))
                filtered_brightness = None
                logger.info('[TWILIGHT ENTRY FROM DAY] Inherited Exp=%dus Gain=%.2f', manual_exposure_us, manual_gain)
            else:
                logger.info('[TWILIGHT ENTRY FROM LOW LIGHT] Inherited Exp=%sus Gain=%s Filtered=%s', manual_exposure_us, manual_gain, filtered_brightness)
        elif required_mode == 'DAY':
            night_colour_gains = None
            awb_gain_history.clear()
            mode_control_pending = False
            mode_transition_target_exposure_us = None
    controls_to_apply = build_camera_controls(required_mode)
    with camera_lock:
        picam2.set_controls(controls_to_apply)
    
    current_camera_mode = required_mode
    logger.info('[MODE APPLY] Mode=%s AE=%s AWB=%s Sharp=%.2f', required_mode, controls_to_apply.get('AeEnable'), controls_to_apply.get('AwbEnable'), controls_to_apply.get('Sharpness', 1.0))
    if mode_changed:
        logger.info('[CAMERA] %s -> %s | Sun %.2f degrees', previous_mode or 'START', current_camera_mode, current_solar_elevation)
        audit_event('camera_mode_change', previous_mode=previous_mode or 'START', new_mode=current_camera_mode, night_awb_locked=night_colour_gains is not None)
    else:
        logger.info('[CAMERA] Reapplied %s controls | Sun %.2f degrees', current_camera_mode, current_solar_elevation)
    return True

def check_for_new_day():
    global current_operating_date, cached_sun_date, cached_sunrise, cached_sunset
    today = local_now().date()
    if current_operating_date is None:
        current_operating_date = today
        return
    if today == current_operating_date:
        return
    previous_date = current_operating_date
    current_operating_date = today
    cached_sun_date = cached_sunrise = cached_sunset = None
    logger.info('[NEW DAY] %s -> %s', previous_date, today)
    get_harpenden_sun_times()
    configure_camera_mode(force=True)
