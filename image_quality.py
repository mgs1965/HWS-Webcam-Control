"""V45-TL8-M2 physical module: image_quality.py. Loaded into the shared runtime namespace.
Do not import directly; use weather_camera.py.
"""


def measure_image(image_array):
    """Calculate weighted scene brightness, contrast, highlights and shadows.

    The sampled image is divided vertically into sky, horizon and foreground.
    Brightness is weighted 60/30/10 percent respectively so exposure decisions
    primarily follow the weather/sky region rather than the dark foreground.
    """
    sample = image_array[::METERING_STEP, ::METERING_STEP, :3].astype(np.float32)
    height = sample.shape[0]
    sky_end = int(height * 0.6)
    horizon_end = int(height * 0.85)
    luminance = sample[:, :, 0] * 0.2126 + sample[:, :, 1] * 0.7152 + sample[:, :, 2] * 0.0722
    sky = luminance[:sky_end, :]
    horizon = luminance[sky_end:horizon_end, :]
    foreground = luminance[horizon_end:, :]
    sky_value = float(np.percentile(sky, METERING_PERCENTILE))
    horizon_value = float(np.percentile(horizon, METERING_PERCENTILE))
    foreground_value = float(np.percentile(foreground, METERING_PERCENTILE))
    brightness = sky_value * SKY_WEIGHT + horizon_value * HORIZON_WEIGHT + foreground_value * FOREGROUND_WEIGHT
    sky_horizon = np.concatenate((sky.ravel(), horizon.ravel()))
    horizontal = np.abs(np.diff(luminance, axis=1))
    vertical = np.abs(np.diff(luminance, axis=0))
    sharpness = (float(np.mean(horizontal)) + float(np.mean(vertical))) / 2.0
    edge_density = (float(np.mean(horizontal >= QUALITY_EDGE_THRESHOLD)) + float(np.mean(vertical >= QUALITY_EDGE_THRESHOLD))) * 50.0
    return {'brightness': brightness, 'sky': sky_value, 'horizon': horizon_value, 'foreground': foreground_value, 'contrast': float(np.std(luminance)), 'highlights': float(np.mean(sky_horizon >= HIGHLIGHT_THRESHOLD) * 100.0), 'shadows': float(np.mean(luminance <= SHADOW_THRESHOLD) * 100.0), 'sharpness_score': sharpness, 'edge_density': edge_density}

def classify_night_quality(measurement, brightness, highlights):
    """Label a NIGHT frame GOOD, DARK, NOISY or WASHED and log changes."""
    global night_quality_state
    gain = float(manual_gain or 0.0)
    if brightness >= NIGHT_QUALITY_WASH_BRIGHTNESS or highlights > NIGHT_MAX_HIGHLIGHT_PERCENT:
        label = 'WASHED'
    elif brightness < NIGHT_OBSERVABILITY_MIN_BRIGHTNESS:
        label = 'DARK'
    elif gain >= NIGHT_QUALITY_NOISY_GAIN:
        label = 'NOISY'
    else:
        label = 'GOOD'
    measurement['night_quality'] = label
    if label != night_quality_state:
        logger.info('[NIGHT QUALITY] %s -> %s | B=%.1f | Gain=%.2f | Highlights=%.2f%%', night_quality_state, label, brightness, gain, highlights)
        if label != 'GOOD':
            audit_event('night_quality_' + label.lower(), severity='INFO', brightness=round(brightness, 1), gain=round(gain, 2), highlights=round(highlights, 2))
        night_quality_state = label
    return label

def update_night_observability(measurement):
    """Gate NIGHT quality only after the camera is genuinely light-limited."""
    global night_observability_open, night_observability_recovery_streak
    global night_observability_failure_streak, night_quality_state
    if current_camera_mode != 'NIGHT':
        night_observability_open = True
        night_observability_recovery_streak = 0
        night_observability_failure_streak = 0
        measurement['night_observability'] = 'N/A'
        measurement['night_quality'] = 'N/A'
        night_quality_state = 'N/A'
        return True
    brightness = float(measurement.get('filtered_brightness', measurement.get('brightness', 0.0)))
    contrast = float(measurement.get('contrast', 0.0))
    edge_density = float(measurement.get('edge_density', 0.0))
    history = sharpness_history['NIGHT']
    baseline = float(np.median(history)) if len(history) >= QUALITY_BASELINE_MINIMUM_SAMPLES else None
    sharpness_ratio = float(measurement.get('sharpness_score', 0.0)) / baseline if baseline and baseline > 0 else None
    exposure_limited = (manual_exposure_us or 0) >= MAX_NIGHT_EXPOSURE_US - 50000
    gain_limited = (manual_gain or 0.0) >= ABSOLUTE_MAX_GAIN - 0.01
    light_limited = exposure_limited and gain_limited and brightness < NIGHT_OBSERVABILITY_MIN_BRIGHTNESS
    observable_signal = (
        brightness >= NIGHT_OBSERVABILITY_MIN_BRIGHTNESS
        and contrast >= NIGHT_OBSERVABILITY_MIN_CONTRAST
        and edge_density >= NIGHT_OBSERVABILITY_MIN_EDGE_DENSITY
        and (sharpness_ratio is None or sharpness_ratio >= NIGHT_OBSERVABILITY_MIN_SHARPNESS_RATIO)
    )
    observable_now = observable_signal or not light_limited
    previous = night_observability_open
    if observable_now:
        night_observability_failure_streak = 0
        night_observability_recovery_streak += 1
        if night_observability_recovery_streak >= NIGHT_OBSERVABILITY_RECOVERY_CAPTURES:
            night_observability_open = True
    else:
        night_observability_recovery_streak = 0
        night_observability_failure_streak += 1
        if night_observability_failure_streak >= NIGHT_OBSERVABILITY_FAILURE_CAPTURES:
            night_observability_open = False
    measurement['night_observability'] = 'OPEN' if night_observability_open else 'GATED'
    measurement['night_observability_recovery_streak'] = night_observability_recovery_streak
    measurement['night_observability_failure_streak'] = night_observability_failure_streak
    measurement['night_light_limited'] = light_limited
    classify_night_quality(measurement, brightness, float(measurement.get('highlights', 0.0)))
    if previous != night_observability_open:
        logger.info(
            '[NIGHT OBSERVABILITY] %s | LightLimited=%s | B=%.1f/%.1f | C=%.1f/%.1f | ED=%.2f/%.2f | SR=%s/%.2f',
            'OPEN' if night_observability_open else 'GATED', light_limited,
            brightness, NIGHT_OBSERVABILITY_MIN_BRIGHTNESS, contrast,
            NIGHT_OBSERVABILITY_MIN_CONTRAST, edge_density,
            NIGHT_OBSERVABILITY_MIN_EDGE_DENSITY,
            f'{sharpness_ratio:.2f}' if sharpness_ratio is not None else '--',
            NIGHT_OBSERVABILITY_MIN_SHARPNESS_RATIO,
        )
        audit_event(
            'night_observability_' + ('open' if night_observability_open else 'gated'),
            brightness=round(brightness, 2), contrast=round(contrast, 2),
            edge_density=round(edge_density, 3),
            sharpness_ratio=round(sharpness_ratio, 3) if sharpness_ratio is not None else None,
            light_limited=light_limited,
        )
    return night_observability_open

def update_image_quality(measurement):
    """Calculate quality, protect baselines, and manage persistent alerts."""
    global quality_warning_streak, quality_critical_streak
    global quality_recovery_streak, quality_alert_level, quality_alert_started
    global quality_tracking_mode, quality_mode_capture_count
    global day_fresh_sharpness_samples, day_baseline_validated, day_baseline_source, day_baseline_candidate
    if quality_tracking_mode != current_camera_mode:
        if quality_alert_level is not None:
            now = local_now()
            duration = (now - quality_alert_started).total_seconds() if quality_alert_started is not None else None
            logger.info('[IMAGE QUALITY] CLOSED ON MODE CHANGE | %s -> %s | Previous=%s | Duration=%.0fs', quality_tracking_mode, current_camera_mode, quality_alert_level, duration or 0.0)
            audit_event('image_quality_alert_closed_on_mode_change', previous_mode=quality_tracking_mode, new_mode=current_camera_mode, previous_alert=quality_alert_level, duration_seconds=round(duration, 1) if duration is not None else None)
        quality_tracking_mode = current_camera_mode
        quality_mode_capture_count = 0
        day_fresh_sharpness_samples = []
        day_baseline_validated = current_camera_mode != 'DAY'
        day_baseline_source = 'validating' if current_camera_mode == 'DAY' else 'history'
        day_baseline_candidate = None
        quality_warning_streak = 0
        quality_critical_streak = 0
        quality_recovery_streak = 0
        quality_alert_level = None
        quality_alert_started = None
    history = sharpness_history[current_camera_mode]
    sharpness = float(measurement['sharpness_score'])
    quality_mode_capture_count += 1
    if quality_mode_capture_count <= QUALITY_MODE_SETTLE_CAPTURES:
        measurement['night_observability'] = 'SETTLING' if current_camera_mode == 'NIGHT' else 'N/A'
        measurement.update({
            'sharpness_baseline': None,
            'sharpness_ratio': None,
            'image_quality_score': None,
            'image_quality_status': 'SETTLING',
            'quality_learning_samples': len(history),
            'quality_learning_required': QUALITY_BASELINE_MINIMUM_SAMPLES,
            'quality_settling_capture': quality_mode_capture_count,
            'quality_settling_required': QUALITY_MODE_SETTLE_CAPTURES,
            'lens_status': 'SETTLING',
        })
        return
    observability_open = update_night_observability(measurement)
    if current_camera_mode == 'NIGHT' and not observability_open:
        if quality_alert_level is not None:
            logger.info('[IMAGE QUALITY] SUSPENDED | Mode=NIGHT | Previous=%s | Reason=UNOBSERVABLE', quality_alert_level)
            audit_event('image_quality_alert_suspended', previous_alert=quality_alert_level, reason='night_unobservable')
        quality_warning_streak = 0
        quality_critical_streak = 0
        quality_recovery_streak = 0
        quality_alert_level = None
        quality_alert_started = None
        baseline = float(np.median(history)) if len(history) >= QUALITY_BASELINE_MINIMUM_SAMPLES else None
        ratio = sharpness / baseline if baseline and baseline > 0 else None
        measurement.update({
            'sharpness_baseline': baseline,
            'sharpness_ratio': ratio,
            'image_quality_score': None,
            'image_quality_status': 'UNOBSERVABLE',
            'quality_learning_samples': len(history),
            'quality_learning_required': QUALITY_BASELINE_MINIMUM_SAMPLES,
            'lens_status': 'UNOBSERVABLE',
        })
        return
    baseline = float(np.median(history)) if len(history) >= QUALITY_BASELINE_MINIMUM_SAMPLES else None
    if current_camera_mode == 'DAY' and not day_baseline_validated:
        day_fresh_sharpness_samples.append(sharpness)
        if len(day_fresh_sharpness_samples) < QUALITY_FRESH_VALIDATION_SAMPLES:
            measurement.update({'sharpness_baseline': None,'sharpness_ratio': None,'image_quality_score': None,'image_quality_status': 'LEARNING','quality_learning_samples': len(day_fresh_sharpness_samples),'quality_learning_required': QUALITY_FRESH_VALIDATION_SAMPLES,'lens_status': 'LEARNING'})
            return
        day_baseline_candidate=float(np.median(day_fresh_sharpness_samples[-QUALITY_FRESH_VALIDATION_SAMPLES:]))
        if baseline is None or baseline > day_baseline_candidate*QUALITY_STORED_BASELINE_MAX_ABOVE_FRESH:
            history.clear(); history.extend(day_fresh_sharpness_samples[-QUALITY_FRESH_VALIDATION_SAMPLES:]); baseline=day_baseline_candidate; save_quality_state(); day_baseline_source='fresh-replacement'
            logger.warning('[IMAGE QUALITY] DAY stored baseline rejected | Fresh=%.2f',day_baseline_candidate)
        else: day_baseline_source='stored-validated'
        day_baseline_validated=True
        logger.info('[IMAGE QUALITY] DAY baseline validated | Source=%s | Baseline=%.2f',day_baseline_source,baseline)
    if baseline is None:
        history.append(sharpness)
        if len(history) == QUALITY_BASELINE_MINIMUM_SAMPLES:
            save_quality_state()
        measurement.update({'sharpness_baseline': None, 'sharpness_ratio': None, 'image_quality_score': None, 'image_quality_status': 'LEARNING', 'quality_learning_samples': len(history), 'quality_learning_required': QUALITY_BASELINE_MINIMUM_SAMPLES, 'lens_status': 'LEARNING'})
        return
    sharpness_ratio = sharpness / baseline if baseline > 0 else 1.0
    contrast_limit = {'DAY': DAY_CONTRAST_WARNING, 'TWILIGHT': TWILIGHT_CONTRAST_WARNING, 'LOW LIGHT': LOW_LIGHT_CONTRAST_WARNING, 'NIGHT': NIGHT_CONTRAST_WARNING}[current_camera_mode]
    at_exposure_limit = current_camera_mode != 'DAY' and (manual_exposure_us or 0) >= maximum_exposure_for_mode(current_camera_mode) - 50000
    at_gain_limit = current_camera_mode != 'DAY' and (manual_gain or 0.0) >= ABSOLUTE_MAX_GAIN - 0.01
    brightness_in_target = measurement.get('target_low', float('-inf')) <= measurement.get('filtered_brightness', measurement['brightness']) <= measurement.get('target_high', float('inf'))
    controls_stable = current_camera_mode == 'DAY' or (current_exposure_action == 'HOLD' and pending_control_captures == 0 and not mode_control_pending)
    baseline_update_allowed = sharpness_ratio >= QUALITY_WARNING_RATIO and measurement['contrast'] >= contrast_limit and (measurement['highlights'] <= 10.0) and (not (at_exposure_limit and at_gain_limit)) and brightness_in_target and controls_stable
    if baseline_update_allowed:
        history.append(sharpness)
    quality_score = 100.0 * (0.5 * clamp(sharpness_ratio, 0.0, 1.0) + 0.25 * clamp(measurement['contrast'] / max(contrast_limit * 2.0, 1.0), 0.0, 1.0) + 0.15 * clamp(1.0 - measurement['highlights'] / 20.0, 0.0, 1.0) + 0.1 * clamp(1.0 - measurement['shadows'] / 90.0, 0.0, 1.0))
    if sharpness_ratio < QUALITY_CRITICAL_RATIO or quality_score < 40.0:
        quality_status = 'CRITICAL'
    elif sharpness_ratio < QUALITY_WARNING_RATIO or quality_score < 60.0:
        quality_status = 'WARNING'
    elif quality_score < 75.0:
        quality_status = 'FAIR'
    else:
        quality_status = 'GOOD'
    if sharpness_ratio < QUALITY_CRITICAL_RATIO:
        quality_critical_streak += 1
        quality_warning_streak += 1
        quality_recovery_streak = 0
    elif sharpness_ratio < QUALITY_WARNING_RATIO:
        quality_warning_streak += 1
        quality_critical_streak = 0
        quality_recovery_streak = 0
    else:
        quality_warning_streak = 0
        quality_critical_streak = 0
        if quality_alert_level and sharpness_ratio >= QUALITY_RECOVERY_RATIO:
            quality_recovery_streak += 1
        else:
            quality_recovery_streak = 0
    now = local_now()
    requested_alert = None
    if quality_critical_streak >= QUALITY_CRITICAL_CONSECUTIVE:
        requested_alert = 'CRITICAL'
    elif quality_warning_streak >= QUALITY_WARNING_CONSECUTIVE:
        requested_alert = 'WARNING'
    if requested_alert and requested_alert != quality_alert_level:
        if quality_alert_started is None:
            quality_alert_started = now
        quality_alert_level = requested_alert
        logger.warning('[IMAGE QUALITY] %s | Mode=%s | SR=%.2f | Q=%.1f | Consecutive=%d', requested_alert, current_camera_mode, sharpness_ratio, quality_score, quality_critical_streak if requested_alert == 'CRITICAL' else quality_warning_streak)
        audit_event('image_quality_degraded', severity=requested_alert, mode=current_camera_mode, sharpness_ratio=round(sharpness_ratio, 3), quality_score=round(quality_score, 1))
    elif quality_alert_level and quality_recovery_streak >= QUALITY_RECOVERY_CONSECUTIVE:
        duration = (now - quality_alert_started).total_seconds() if quality_alert_started else None
        logger.info('[IMAGE QUALITY] RECOVERED | Mode=%s | SR=%.2f | Q=%.1f | Duration=%.0fs', current_camera_mode, sharpness_ratio, quality_score, duration or 0.0)
        audit_event('image_quality_recovered', mode=current_camera_mode, sharpness_ratio=round(sharpness_ratio, 3), quality_score=round(quality_score, 1), duration_seconds=round(duration, 1) if duration is not None else None)
        quality_alert_level = None
        quality_alert_started = None
        quality_recovery_streak = 0
    if quality_alert_level == 'CRITICAL':
        lens_status = 'POSSIBLE OBSTRUCTION'
    elif quality_alert_level == 'WARNING' or quality_status in ('WARNING', 'CRITICAL'):
        lens_status = 'DEGRADED'
    else:
        lens_status = 'CLEAR'
    measurement.update({'sharpness_baseline': baseline, 'sharpness_ratio': sharpness_ratio, 'image_quality_score': quality_score, 'image_quality_status': quality_status, 'quality_learning_samples': QUALITY_BASELINE_MINIMUM_SAMPLES, 'quality_learning_required': QUALITY_BASELINE_MINIMUM_SAMPLES, 'lens_status': lens_status})
