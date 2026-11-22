"""V54.0 physical module: scene_analysis.py. Loaded into the shared runtime namespace.
Do not import directly; use weather_camera.py.

Observational scene intelligence: sky/cloud estimate, fog and haze, lens
droplets, frozen or blocked views, focus drift and optional weather-station
data. Nothing here changes camera control or the immutable telemetry-v4
contract; results are published through the status file and a separate
scene-history log.
"""

SCENE_ANALYSIS_ENABLED = True
SCENE_ANALYSIS_EVERY_N_CAPTURES = 3
SCENE_HISTORY_EVERY_N_CAPTURES = 6
SCENE_HISTORY_RETENTION_DAYS = 30
SCENE_HISTORY_PATH = os.path.join(LOGS_PATH, 'scene')
SCENE_OVERLAY_ENABLED = True
SCENE_SKY_FRACTION = 0.55
SCENE_SKY_MIN_LUMINANCE = 50.0
SCENE_SKY_MIN_VALID_FRACTION = 0.3
SCENE_CLOUD_RBR_THRESHOLD = 0.80
SCENE_CLOUD_LOW_SUN_ELEVATION = 10.0
SCENE_CLOUD_LOW_SUN_DEVIATION = 0.08
SCENE_CLOUD_LOW_SUN_MIN_ROW_PIXELS = 20
SCENE_OVERCAST_UNIFORM_STD = 0.04
SCENE_OVERCAST_MIN_MEAN_RBR = 0.5
SCENE_FROZEN_STEP = 32
SCENE_FROZEN_CHANGED_FRACTION = 0.002
SCENE_FROZEN_CONSECUTIVE = 12
SCENE_BLOCKED_CONTRAST = 4.0
SCENE_BLOCKED_SHARPNESS = 1.0
SCENE_BLOCKED_CONSECUTIVE = 18
SCENE_FOG_WARNING_INDEX = 35.0
SCENE_FOG_ALERT_INDEX = 60.0
SCENE_FOG_SMOOTHING = 0.3
SCENE_DROPLET_GRID = (6, 4)
SCENE_DROPLET_MIN_TEXTURE = 1.0
SCENE_DROPLET_SMOOTH_RATIO = 0.35
SCENE_DROPLET_EXCESS_ALERT = 25.0
SCENE_DROPLET_CONSECUTIVE = 4
SCENE_DROPLET_BASELINE_LENGTH = 360
SCENE_FOCUS_WINDOW = 360
SCENE_FOCUS_MIN_SAMPLES = 120
SCENE_FOCUS_DRIFT_RATIO = 0.90
SCENE_FOCUS_RECOVERY_RATIO = 0.94
SCENE_OVERLAY_STATION_EXTRAS = os.getenv('HWS_OVERLAY_STATION_EXTRAS', '1') != '0'
SCENE_WEATHER_DATA_PATH = os.getenv('HWS_WEATHER_DATA_PATH', os.path.join(LOGS_PATH, 'weather_station.json'))
SCENE_WEATHER_MAX_AGE_SECONDS = 900
SCENE_WEATHER_CACHE_SECONDS = 30
SCENE_WEATHER_LIMITS = {
    'temperature_c': (-60.0, 60.0),
    'humidity_percent': (0.0, 100.0),
    'pressure_hpa': (850.0, 1100.0),
    'wind_speed_mph': (0.0, 250.0),
    'wind_gust_mph': (0.0, 250.0),
    'wind_direction_deg': (0.0, 360.0),
    'rain_rate_mm_h': (0.0, 500.0),
    'dew_point_c': (-60.0, 60.0),
    'uv_index': (0.0, 20.0),
    'solar_radiation_wm2': (0.0, 1800.0),
    'wind_gust_max_1h_mph': (0.0, 250.0),
    'wind_gust_max_today_mph': (0.0, 250.0),
    'lightning_strikes_last_min': (0.0, 100000.0),
    'lightning_strikes_today': (0.0, 1000000.0),
    'lightning_distance': (0.0, 1000.0),
    'temp_change_1h_c': (-40.0, 40.0),
    'humidity_change_1h': (-100.0, 100.0),
    'pressure_change_1h_hpa': (-50.0, 50.0),
}
SCENE_FOG_RISK_HIGH_SPREAD_C = 1.0
SCENE_FOG_RISK_HIGH_HUMIDITY = 95.0
SCENE_FOG_RISK_MODERATE_SPREAD_C = 2.5
SCENE_FOG_RISK_MODERATE_HUMIDITY = 90.0
SCENE_ALERT_SEVERITY = {
    'FROZEN_IMAGE': 'ERROR', 'BLOCKED_VIEW': 'ERROR', 'LENS_DROPLETS': 'WARNING',
    'FOG': 'WARNING', 'FOCUS_DRIFT': 'WARNING',
}
os.makedirs(SCENE_HISTORY_PATH, exist_ok=True)

scene_capture_counter = 0
scene_previous_thumbnail = None
scene_frozen_streak = 0
scene_blocked_streak = 0
scene_droplet_streak = 0
scene_fog_index = None
scene_droplet_history = deque(maxlen=SCENE_DROPLET_BASELINE_LENGTH)
scene_focus_ratios = deque(maxlen=SCENE_FOCUS_WINDOW)
scene_focus_drifting = False
scene_active_alerts = {}
scene_last_result = None
scene_weather_cache = {'checked': float('-inf'), 'raw': None}


def _scene_luminance(sample):
    return sample[:, :, 0] * 0.2126 + sample[:, :, 1] * 0.7152 + sample[:, :, 2] * 0.0722

def classify_cloud_cover(cloud_pct):
    if cloud_pct is None:
        return 'N/A'
    if cloud_pct < 10.0:
        return 'CLEAR'
    if cloud_pct < 30.0:
        return 'MOSTLY CLEAR'
    if cloud_pct < 60.0:
        return 'PARTLY CLOUDY'
    if cloud_pct < 90.0:
        return 'MOSTLY CLOUDY'
    return 'OVERCAST'

def estimate_cloud_cover(sample, low_sun=False):
    """Return the cloudy share of valid sky pixels (red/blue ratio method) or None.

    With the sun low, a clear sky is warm near the horizon and passes the fixed
    ratio test, so clouds are instead the pixels whose ratio departs from the
    median of their own row (a clear sky varies mostly with height).
    """
    sky = sample[:max(1, int(sample.shape[0] * SCENE_SKY_FRACTION))]
    valid = _scene_luminance(sky) >= SCENE_SKY_MIN_LUMINANCE
    if float(valid.mean()) < SCENE_SKY_MIN_VALID_FRACTION:
        return None
    red = sky[:, :, 0][valid]
    blue = sky[:, :, 2][valid]
    ratio = red / np.maximum(blue, 1.0)
    if float(ratio.std()) < SCENE_OVERCAST_UNIFORM_STD and float(ratio.mean()) > SCENE_OVERCAST_MIN_MEAN_RBR:
        return 100.0
    if low_sun:
        ratios = sky[:, :, 0] / np.maximum(sky[:, :, 2], 1.0)
        cloudy = total = 0
        for row, ok in zip(ratios, valid):
            if int(ok.sum()) < SCENE_CLOUD_LOW_SUN_MIN_ROW_PIXELS:
                continue
            values = row[ok]
            cloudy += int(np.sum(np.abs(values - np.median(values)) > SCENE_CLOUD_LOW_SUN_DEVIATION))
            total += values.size
        return float(cloudy / total * 100.0) if total else None
    return float(np.mean(ratio > SCENE_CLOUD_RBR_THRESHOLD) * 100.0)

def estimate_fog_index(measurement):
    """Blend of sharpness loss and low contrast, 0 (clear) to 100 (dense fog)."""
    ratio = measurement.get('sharpness_ratio')
    if ratio is None:
        return None
    contrast_loss = clamp(1.0 - float(measurement.get('contrast', 0.0)) / (DAY_CONTRAST_WARNING * 2.0), 0.0, 1.0)
    sharpness_loss = clamp((0.95 - float(ratio)) / 0.5, 0.0, 1.0)
    return 100.0 * (0.6 * sharpness_loss + 0.4 * contrast_loss)

def estimate_droplet_score(sample):
    """Percentage of textured lower-scene blocks that are unusually smooth."""
    luminance = _scene_luminance(sample)
    region = luminance[int(luminance.shape[0] * 0.5):]
    columns, rows = SCENE_DROPLET_GRID
    block_h, block_w = region.shape[0] // rows, region.shape[1] // columns
    if block_h < 4 or block_w < 4:
        return None
    energies = []
    for row in range(rows):
        for column in range(columns):
            block = region[row * block_h:(row + 1) * block_h, column * block_w:(column + 1) * block_w]
            energies.append(float(np.mean(np.abs(np.diff(block, axis=1))) + np.mean(np.abs(np.diff(block, axis=0)))))
    median = float(np.median(energies))
    if median < SCENE_DROPLET_MIN_TEXTURE:
        return None
    return float(np.mean(np.asarray(energies) < median * SCENE_DROPLET_SMOOTH_RATIO) * 100.0)

def update_frozen_detection(image_array):
    """Count consecutive captures whose sampled pixels are effectively identical."""
    global scene_previous_thumbnail, scene_frozen_streak
    thumbnail = np.ascontiguousarray(image_array[::SCENE_FROZEN_STEP, ::SCENE_FROZEN_STEP, :3])
    previous = scene_previous_thumbnail
    scene_previous_thumbnail = thumbnail
    if previous is None or previous.shape != thumbnail.shape:
        scene_frozen_streak = 0
    elif float(np.mean(previous != thumbnail)) < SCENE_FROZEN_CHANGED_FRACTION:
        scene_frozen_streak += 1
    else:
        scene_frozen_streak = 0
    return scene_frozen_streak >= SCENE_FROZEN_CONSECUTIVE

def update_blocked_detection(measurement):
    """Detect a near-uniform image while there is enough light to see a scene."""
    global scene_blocked_streak
    if current_camera_mode not in ('DAY', 'TWILIGHT'):
        scene_blocked_streak = 0
        return False
    uniform = float(measurement.get('contrast', 0.0)) < SCENE_BLOCKED_CONTRAST and float(measurement.get('sharpness_score', 0.0)) < SCENE_BLOCKED_SHARPNESS
    scene_blocked_streak = scene_blocked_streak + 1 if uniform else 0
    return scene_blocked_streak >= SCENE_BLOCKED_CONSECUTIVE

def update_focus_drift(measurement, clear_conditions):
    """Flag a sustained, mild sharpness decline that quality alerts do not catch."""
    global scene_focus_drifting
    ratio = measurement.get('sharpness_ratio')
    if current_camera_mode != 'DAY' or ratio is None or not clear_conditions:
        return scene_focus_drifting, len(scene_focus_ratios)
    scene_focus_ratios.append(float(ratio))
    if len(scene_focus_ratios) < SCENE_FOCUS_MIN_SAMPLES:
        return False, len(scene_focus_ratios)
    median = float(np.median(scene_focus_ratios))
    if scene_focus_drifting:
        scene_focus_drifting = median < SCENE_FOCUS_RECOVERY_RATIO
    else:
        scene_focus_drifting = QUALITY_CRITICAL_RATIO <= median < SCENE_FOCUS_DRIFT_RATIO
    return scene_focus_drifting, len(scene_focus_ratios)

def set_scene_alert(name, active, **details):
    """Log and audit alert transitions once; return True when the alert is active."""
    was_active = name in scene_active_alerts
    if active and not was_active:
        scene_active_alerts[name] = local_now().isoformat()
        logger.warning('[SCENE] %s detected | %s', name, details)
        audit_event('scene_alert_' + name.lower(), severity=SCENE_ALERT_SEVERITY[name], **details)
    elif not active and was_active:
        started = scene_active_alerts.pop(name)
        logger.info('[SCENE] %s cleared | Since=%s', name, started)
        audit_event('scene_alert_cleared', name=name, since=started)
    return active

def _bounded_weather_value(raw, key):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    low, high = SCENE_WEATHER_LIMITS[key]
    return round(value, 2) if math.isfinite(value) and low <= value <= high else None

def parse_weather_data(data, now):
    """Validate a weather-station JSON object; return None if unusable or stale."""
    if not isinstance(data, dict):
        return None
    try:
        updated = datetime.fromisoformat(str(data.get('updated')))
    except ValueError:
        return None
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=now.tzinfo)
    age = (now - updated).total_seconds()
    if age > SCENE_WEATHER_MAX_AGE_SECONDS or age < -60:
        return None
    values = {key: _bounded_weather_value(data.get(key), key) for key in SCENE_WEATHER_LIMITS}
    values = {key: value for key, value in values.items() if value is not None}
    if not values:
        return None
    values['age_seconds'] = max(0, int(age))
    return values

def read_weather_data():
    """Read the optional weather-station file at most every cache interval."""
    cache = scene_weather_cache
    now_monotonic = time.monotonic()
    if now_monotonic - cache['checked'] >= SCENE_WEATHER_CACHE_SECONDS:
        cache['checked'] = now_monotonic
        try:
            with open(SCENE_WEATHER_DATA_PATH, 'r', encoding='utf-8') as source:
                cache['raw'] = json.load(source)
        except (OSError, ValueError):
            cache['raw'] = None
    return parse_weather_data(cache['raw'], local_now())

def weather_fog_risk(weather):
    """Fog likelihood from air/dew-point spread and humidity; None without both inputs."""
    if not weather:
        return None
    humidity = weather.get('humidity_percent')
    temperature = weather.get('temperature_c')
    dew_point = weather.get('dew_point_c')
    if dew_point is None and temperature is not None and humidity is not None and humidity > 0:
        gamma = math.log(humidity / 100.0) + 17.62 * temperature / (243.12 + temperature)
        dew_point = 243.12 * gamma / (17.62 - gamma)
    if temperature is None or dew_point is None or humidity is None:
        return None
    spread = temperature - dew_point
    if spread <= SCENE_FOG_RISK_HIGH_SPREAD_C and humidity >= SCENE_FOG_RISK_HIGH_HUMIDITY:
        return 'HIGH'
    if spread <= SCENE_FOG_RISK_MODERATE_SPREAD_C and humidity >= SCENE_FOG_RISK_MODERATE_HUMIDITY:
        return 'MODERATE'
    return 'LOW'

def format_weather_overlay(weather):
    if not weather:
        return None
    parts = []
    if 'temperature_c' in weather:
        parts.append(f"{weather['temperature_c']:.1f}C")
    if 'humidity_percent' in weather:
        parts.append(f"{weather['humidity_percent']:.0f}%")
    if 'pressure_hpa' in weather:
        parts.append(f"{weather['pressure_hpa']:.0f}hPa")
    if 'wind_speed_mph' in weather:
        parts.append(f"Wind {weather['wind_speed_mph']:.0f}mph")
    if weather.get('rain_rate_mm_h', 0) > 0:
        parts.append(f"Rain {weather['rain_rate_mm_h']:.1f}mm/h")
    if SCENE_OVERLAY_STATION_EXTRAS:
        if weather.get('wind_gust_mph') and weather['wind_gust_mph'] >= 10:
            parts.append(f"Gust {weather['wind_gust_mph']:.0f}mph")
        if weather.get('solar_radiation_wm2', 0) > 0:
            parts.append(f"Solar {weather['solar_radiation_wm2']:.0f}W/m2")
        if weather.get('uv_index', 0) > 0:
            parts.append(f"UV {weather['uv_index']:.1f}")
        if weather.get('lightning_strikes_last_min', 0) > 0:
            parts.append(f"Lightning {weather['lightning_strikes_last_min']:.0f}")
    return ' | '.join(parts) or None

def summarise_scene(result):
    for alert, text in (('FROZEN_IMAGE', 'Frozen image'), ('BLOCKED_VIEW', 'View blocked'), ('LENS_DROPLETS', 'Lens droplets'), ('FOG', 'Fog')):
        if alert in result['alerts']:
            return text
    if result['visibility'] == 'HAZE':
        return 'Hazy'
    return result['sky_condition'].title() if result['sky_condition'] != 'N/A' else None

def update_scene_analysis(image_array, measurement):
    """Analyse one capture; results go to measurement['scene'] / ['weather']."""
    global scene_capture_counter, scene_droplet_streak, scene_fog_index, scene_last_result
    if not SCENE_ANALYSIS_ENABLED:
        return None
    scene_capture_counter += 1
    weather = read_weather_data()
    measurement['weather'] = weather
    frozen = set_scene_alert('FROZEN_IMAGE', update_frozen_detection(image_array), consecutive_captures=scene_frozen_streak)
    blocked = set_scene_alert('BLOCKED_VIEW', update_blocked_detection(measurement), contrast=round(float(measurement.get('contrast', 0.0)), 2))
    if scene_last_result is not None and scene_capture_counter % SCENE_ANALYSIS_EVERY_N_CAPTURES != 0:
        result = dict(scene_last_result, alerts=sorted(scene_active_alerts), frozen=frozen, blocked=blocked, fog_risk=weather_fog_risk(weather))
        result['summary'] = summarise_scene(result)
        measurement['scene'] = scene_last_result = result
        return result
    cloud_pct = droplet_score = droplet_excess = None
    daytime = current_camera_mode == 'DAY'
    sample = image_array[::METERING_STEP, ::METERING_STEP, :3].astype(np.float32)
    if daytime:
        elevation = globals().get('current_solar_elevation')
        cloud_pct = estimate_cloud_cover(sample, low_sun=elevation is not None and elevation < SCENE_CLOUD_LOW_SUN_ELEVATION)
        fog_value = estimate_fog_index(measurement)
        if fog_value is not None:
            scene_fog_index = fog_value if scene_fog_index is None else scene_fog_index + SCENE_FOG_SMOOTHING * (fog_value - scene_fog_index)
        droplet_score = estimate_droplet_score(sample)
        if droplet_score is not None:
            baseline = float(np.median(scene_droplet_history)) if len(scene_droplet_history) >= 30 else None
            droplet_excess = droplet_score - baseline if baseline is not None else 0.0
            scene_droplet_history.append(droplet_score)
            scene_droplet_streak = scene_droplet_streak + 1 if droplet_excess >= SCENE_DROPLET_EXCESS_ALERT else 0
    else:
        scene_fog_index = None
        scene_droplet_streak = 0
    fog_index = scene_fog_index
    fogging = daytime and fog_index is not None and fog_index >= SCENE_FOG_ALERT_INDEX
    droplets = set_scene_alert('LENS_DROPLETS', daytime and scene_droplet_streak >= SCENE_DROPLET_CONSECUTIVE, score=None if droplet_score is None else round(droplet_score, 1))
    set_scene_alert('FOG', fogging, fog_index=None if fog_index is None else round(fog_index, 1))
    drifting, focus_samples = update_focus_drift(measurement, not droplets and not fogging and (fog_index or 0.0) < SCENE_FOG_WARNING_INDEX)
    set_scene_alert('FOCUS_DRIFT', drifting, samples=focus_samples)
    raining = bool(weather and weather.get('rain_rate_mm_h', 0) > 0)
    if not daytime or fog_index is None:
        visibility = 'N/A'
    elif fog_index >= SCENE_FOG_ALERT_INDEX:
        visibility = 'FOG'
    elif fog_index >= SCENE_FOG_WARNING_INDEX:
        visibility = 'HAZE'
    else:
        visibility = 'CLEAR'
    if cloud_pct is None:
        clarity = None
    else:
        clarity = round(clamp(100.0 - cloud_pct * 0.6 - (fog_index or 0.0) * 0.4, 0.0, 100.0), 1)
    result = {
        'cloud_cover_pct': None if cloud_pct is None else round(cloud_pct, 1),
        'sky_condition': classify_cloud_cover(cloud_pct),
        'sky_clarity_pct': clarity,
        'fog_index': None if fog_index is None else round(fog_index, 1),
        'visibility': visibility,
        'droplet_score': None if droplet_score is None else round(droplet_score, 1),
        'lens_condition': 'DROPLETS SUSPECTED' if droplets else ('RAIN REPORTED' if raining else ('CLEAR' if daytime else 'N/A')),
        'frozen': frozen, 'blocked': blocked,
        'focus': 'DRIFT' if drifting else ('OK' if focus_samples >= SCENE_FOCUS_MIN_SAMPLES else 'LEARNING'),
        'alerts': sorted(scene_active_alerts),
        'fog_risk': weather_fog_risk(weather),
        'analysed_at': local_now().isoformat(),
        'mode': current_camera_mode, 'analysis_paused': not daytime,
    }
    result['summary'] = summarise_scene(result)
    measurement['scene'] = scene_last_result = result
    return result

def scene_overlay_texts(measurement):
    """Return (left, right) text for the optional top overlay bar."""
    if not SCENE_OVERLAY_ENABLED:
        return None, None
    scene = measurement.get('scene') or {}
    right = scene.get('summary')
    if scene.get('cloud_cover_pct') is not None and right:
        right = f"{right} | Cloud {scene['cloud_cover_pct']:.0f}%"
    return format_weather_overlay(measurement.get('weather')), right

def record_scene_history(capture_time, measurement):
    """Append a sampled scene record to the daily JSONL history."""
    scene = measurement.get('scene')
    if not scene or scene_capture_counter % SCENE_HISTORY_EVERY_N_CAPTURES != 0:
        return False
    weather = measurement.get('weather') or {}
    record = {'timestamp': capture_time.isoformat(), 'mode': current_camera_mode}
    record.update({key: scene.get(key) for key in ('cloud_cover_pct', 'sky_clarity_pct', 'fog_index', 'visibility', 'droplet_score', 'lens_condition', 'focus', 'alerts', 'fog_risk')})
    record.update({key: weather.get(key) for key in ('temperature_c', 'humidity_percent', 'pressure_hpa', 'wind_speed_mph', 'wind_direction_deg', 'wind_gust_mph', 'rain_rate_mm_h', 'rain_today_mm', 'dew_point_c', 'uv_index', 'solar_radiation_wm2', 'temp_change_1h_c', 'humidity_change_1h', 'pressure_change_1h_hpa')})
    filename = os.path.join(SCENE_HISTORY_PATH, f'scene_{capture_time:%Y%m%d}.jsonl')
    try:
        with open(filename, 'a', encoding='utf-8') as output:
            output.write(json.dumps(record, separators=(',', ':')) + '\n')
        return True
    except OSError:
        logger.exception('[SCENE] Could not append %s', filename)
        return False

def cleanup_old_scene_history():
    cutoff = (local_now() - timedelta(days=SCENE_HISTORY_RETENTION_DAYS)).timestamp()
    for filename in glob.glob(os.path.join(SCENE_HISTORY_PATH, 'scene_*.jsonl')):
        try:
            if os.path.getmtime(filename) < cutoff:
                os.remove(filename)
        except OSError:
            logger.warning('[STORAGE] Could not process %s', filename)
