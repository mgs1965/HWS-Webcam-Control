"""V45-TL8-M2 physical module: monitoring.py. Loaded into the shared runtime namespace.
Do not import directly; use weather_camera.py.
"""


def validate_storage_paths():
    for directory in (LOCAL_SAVE_PATH, LOGS_PATH, FRAMES_PATH, TIMELAPSE_PATH, HOURLY_SEGMENTS_PATH):
        if not os.path.isdir(directory):
            raise RuntimeError(f'Required storage directory is missing: {directory}')
        probe = os.path.join(directory, '.weather_camera_write_test')
        try:
            with open(probe, 'w', encoding='utf-8') as output:
                output.write('ok')
                output.flush()
                os.fsync(output.fileno())
            os.remove(probe)
        except OSError as error:
            raise RuntimeError(f'Storage directory is not writable: {directory}: {error}') from error
    logger.info('[STORAGE] Validated writable storage paths under %s', LOCAL_SAVE_PATH)

def validate_v50_configuration():
    """Fail closed on unsafe runtime configuration before workers start."""
    checks = (
        (CAPTURE_INTERVAL_SECONDS >= 1, 'CAPTURE_INTERVAL_SECONDS must be at least 1'),
        (MIN_EXPOSURE_US > 0, 'MIN_EXPOSURE_US must be positive'),
        (0 < MAX_GAIN_CHANGE_FRACTION <= 1, 'MAX_GAIN_CHANGE_FRACTION must be in (0, 1]'),
        (0 < MAX_EXPOSURE_CHANGE_FRACTION <= 1, 'MAX_EXPOSURE_CHANGE_FRACTION must be in (0, 1]'),
        (MIN_ANALOGUE_GAIN >= 1.0, 'MIN_ANALOGUE_GAIN must be at least 1.0'),
        (ABSOLUTE_MAX_GAIN >= MIN_ANALOGUE_GAIN, 'ABSOLUTE_MAX_GAIN is below MIN_ANALOGUE_GAIN'),
        (FTP_MAX_RETRIES >= 1, 'FTP_MAX_RETRIES must be at least 1'),
        (MAX_CONSECUTIVE_CAPTURE_FAILURES >= 1, 'MAX_CONSECUTIVE_CAPTURE_FAILURES must be at least 1'),
        (len(TELEMETRY_FIELDS) == 58, 'telemetry-v4 contract must contain 58 fields'),
    )
    for valid, message in checks:
        if not valid:
            raise RuntimeError(f'V50 configuration validation failed: {message}')
    logger.info('[V50 CONFIG] Runtime and telemetry-v4 safety checks passed')

def get_free_space_gb():
    return shutil.disk_usage(LOCAL_SAVE_PATH).free / 1024 ** 3

def get_cpu_temperature_c():
    """Return Raspberry Pi CPU temperature, or None when unavailable."""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r', encoding='ascii') as source:
            return round(float(source.read().strip()) / 1000.0, 1)
    except (OSError, ValueError):
        return None

def cleanup_incomplete_timelapse_files():
    """Remove abandoned TL3 work files older than the configured safety window."""
    cutoff = (local_now() - timedelta(hours=TIMELAPSE_TEMP_FILE_MAX_AGE_HOURS)).timestamp()
    removed = reclaimed = 0
    patterns = ('*.tmp.mp4', '*.concat.txt', '*.segments.txt', '*.tmp')
    for root in (TIMELAPSE_PATH, HOURLY_SEGMENTS_PATH):
        for pattern in patterns:
            for filename in glob.glob(os.path.join(root, '**', pattern), recursive=True):
                try:
                    if os.path.getmtime(filename) >= cutoff:
                        continue
                    size = os.path.getsize(filename)
                    os.remove(filename); removed += 1; reclaimed += size
                except FileNotFoundError:
                    pass
                except OSError:
                    logger.exception('[TIMELAPSE CLEANUP] Could not remove %s', filename)
    logger.info('[TIMELAPSE CLEANUP] COMPLETE | Files=%d | Reclaimed=%.1fMB', removed, reclaimed / 1024**2)
    return removed

def compress_previous_month_telemetry():
    current_month = local_now().strftime('%Y%m')
    for filename in glob.glob(os.path.join(LOGS_PATH, f'{TELEMETRY_FILENAME_PREFIX}_*.csv')):
        if current_month in os.path.basename(filename):
            continue
        gz_filename = filename + '.gz'
        try:
            with open(filename, 'rb') as source, gzip.open(gz_filename + '.tmp', 'wb') as target:
                shutil.copyfileobj(source, target)
            os.replace(gz_filename + '.tmp', gz_filename)
            os.remove(filename)
        except OSError:
            logger.exception('[TELEMETRY] Compression failed for %s', filename)

def cleanup_expired_telemetry():
    now = local_now()
    cutoff_index = now.year * 12 + now.month - TELEMETRY_RETENTION_MONTHS
    for filename in glob.glob(os.path.join(LOGS_PATH, f'{TELEMETRY_FILENAME_PREFIX}_*.csv*')):
        basename = os.path.basename(filename)
        try:
            telemetry_suffix = basename[len(TELEMETRY_FILENAME_PREFIX) + 1:]
            if telemetry_suffix.startswith('v') and '_' in telemetry_suffix:
                schema_text, telemetry_suffix = telemetry_suffix.split('_', 1)
                if not schema_text[1:].isdigit():
                    continue
            month_text = telemetry_suffix[:6]
            if len(month_text) != 6 or not month_text.isdigit():
                continue
            year, month = int(month_text[:4]), int(month_text[4:6])
            if not 1 <= month <= 12:
                continue
            file_index = year * 12 + month
        except (ValueError, IndexError):
            continue
        if file_index < cutoff_index:
            try:
                os.remove(filename)
            except OSError:
                logger.exception('[TELEMETRY] Could not remove %s', filename)

def emergency_storage_cleanup():
    """Progressively reclaim old archives as free disk space crosses thresholds."""
    free = get_free_space_gb()
    if free >= DISK_WARNING_GB:
        return
    audit_event('low_disk_space', severity='WARNING', free_space_gb=round(free, 2))
    if free < DISK_AGGRESSIVE_CLEANUP_GB:
        today_prefix = f'frame_{local_now():%Y%m%d}_'
        for filename in sorted(glob.glob(os.path.join(FRAMES_PATH, 'frame_*.jpg')), key=os.path.getmtime):
            if os.path.basename(filename).startswith(today_prefix):
                continue
            try:
                os.remove(filename)
            except OSError:
                pass
            if get_free_space_gb() >= DISK_AGGRESSIVE_CLEANUP_GB:
                break
    if get_free_space_gb() < DISK_CRITICAL_GB:
        for filename in sorted(glob.glob(os.path.join(TIMELAPSE_PATH, 'timelapse_*.mp4')), key=os.path.getmtime):
            try:
                os.remove(filename)
            except OSError:
                pass
            if get_free_space_gb() >= DISK_CRITICAL_GB:
                break

def write_daily_health_summary(day):
    """Write and log the V47.2 daily station-health report."""
    filename = os.path.join(LOGS_PATH, f'daily_health_{day:%Y%m%d}.json')
    baseline = daily_counter_baseline or {key: 0 for key in snapshot_counters()}
    current = snapshot_counters()
    daily = {key: current[key] - baseline.get(key, 0) for key in current}
    expected = int(86400 / CAPTURE_INTERVAL_SECONDS)
    captures = daily.get('capture_count', 0)
    capture_pct = round(captures * 100.0 / expected, 2) if expected else 0.0
    health = 'HEALTHY'
    reasons = []
    critical_keys = ('camera_acquisition_failures','image_processing_failures','storage_failures','telemetry_failures','status_failures','camera_restarts')
    if any(daily.get(k,0) for k in critical_keys): health='DEGRADED'; reasons.append('operational failures')
    if ftp_health_state == 'OUTAGE': health='DEGRADED'; reasons.append('FTP outage')
    if captures and capture_pct < 99.0: health='DEGRADED'; reasons.append('capture completeness below 99%')
    summary = {
      'date': day.isoformat(), 'release': VERSION, 'telemetry_schema': TELEMETRY_SCHEMA_VERSION,
      'overall': health, 'reasons': reasons, 'captures': captures, 'captures_expected': expected,
      'capture_completeness_percent': capture_pct, **daily,
      'mode_transitions': mode_transition_count, 'control_health': globals().get('control_health','N/A'),
      'control_ack_p95_captures': globals().get('control_ack_p95_captures',0),
      'control_pipeline_lag_count': globals().get('control_pipeline_lag_count',0),
      'control_timeout_count': globals().get('control_timeout_count',0),
      'control_superseded_count': globals().get('control_superseded_count',0),
      'ftp_health': ftp_health_state, 'ftp_outage_count': ftp_outage_count, 'ftp_recovery_count': ftp_recovery_count,
      'free_space_gb': round(get_free_space_gb(),2),
      'capture_processing_max_ms': round(capture_processing_max_ms,1),
      'timelapse_local_complete': os.path.exists(os.path.join(TIMELAPSE_PATH,f'timelapse_{day:%Y%m%d}.mp4')),
      'timelapse_publish_complete': last_timelapse_completed_for == day,
      'timelapse_build_method': last_timelapse_build_method, 'timelapse_segments': last_timelapse_segment_count,
      'timelapse_expected_frames': last_timelapse_expected_frames, 'timelapse_source_gaps': last_timelapse_source_gaps,
    }
    temporary=filename+'.tmp'
    with open(temporary,'w',encoding='utf-8') as output:
        json.dump(summary,output,indent=2); output.flush(); os.fsync(output.fileno())
    os.replace(temporary,filename)
    logger.info('[DAILY HEALTH] Date=%s | Release=%s | Captures=%d/%d (%.2f%%) | CameraFail=%d | ProcessingFail=%d | TelemetryFail=%d | FTPFail=%d | FTPHealth=%s | Control=%s | AckP95=%s | Timelapse=%s | Gaps=%d | Overall=%s', day, VERSION, captures, expected, capture_pct, daily.get('camera_acquisition_failures',0), daily.get('image_processing_failures',0), daily.get('telemetry_failures',0), daily.get('ftp_failures',0), ftp_health_state, globals().get('control_health','N/A'), globals().get('control_ack_p95_captures',0), 'COMPLETE' if summary['timelapse_local_complete'] else 'PENDING', len(last_timelapse_source_gaps), health)
    audit_event('daily_health', severity='WARNING' if health!='HEALTHY' else 'INFO', **summary)
    return filename

def update_daily_summary_timelapse_status(day):
    """Update the daily health report without recalculating daily counters."""
    filename = os.path.join(LOGS_PATH, f'daily_health_{day:%Y%m%d}.json')
    try:
        with open(filename, 'r', encoding='utf-8') as source:
            summary = json.load(source)
    except FileNotFoundError:
        summary = {'date': day.isoformat()}
    except (OSError, ValueError, json.JSONDecodeError):
        logger.exception('[DAILY HEALTH] Could not read %s', filename)
        return False
    summary['timelapse_local_complete'] = os.path.exists(os.path.join(TIMELAPSE_PATH, f'timelapse_{day:%Y%m%d}.mp4'))
    summary['timelapse_publish_complete'] = last_timelapse_completed_for == day
    summary['timelapse_build_method'] = last_timelapse_build_method
    summary['timelapse_segments'] = last_timelapse_segment_count
    summary['timelapse_expected_frames'] = last_timelapse_expected_frames
    summary['timelapse_source_gaps'] = last_timelapse_source_gaps
    summary['timelapse_status_updated'] = local_now().isoformat()
    temporary = filename + '.tmp'
    try:
        with open(temporary, 'w', encoding='utf-8') as output:
            json.dump(summary, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, filename)
        return True
    except OSError:
        logger.exception('[DAILY HEALTH] Could not update timelapse status for %s', day)
        return False

def cleanup_old_hourly_segments():
    """Remove dated hourly-segment directories beyond video retention."""
    cutoff = local_now().date() - timedelta(days=VIDEO_RETENTION_DAYS)
    for directory in glob.glob(os.path.join(HOURLY_SEGMENTS_PATH, '[0-9]' * 8)):
        try:
            day = datetime.strptime(os.path.basename(directory), '%Y%m%d').date()
        except ValueError:
            continue
        if day < cutoff:
            try:
                shutil.rmtree(directory)
                logger.info('[HOURLY SEGMENT] Removed expired %s', directory)
            except OSError:
                logger.exception('[HOURLY SEGMENT] Could not remove %s', directory)
            continue
        for partial_filename in glob.glob(os.path.join(directory, 'partial_[0-9][0-9].mp4')):
            hour_text = os.path.basename(partial_filename)[8:10]
            if os.path.exists(os.path.join(directory, f'segment_{hour_text}.mp4')):
                try:
                    os.remove(partial_filename)
                    logger.info('[HOURLY SEGMENT] Housekeeping removed obsolete partial %s', partial_filename)
                except OSError:
                    logger.exception('[HOURLY SEGMENT] Could not remove obsolete partial %s', partial_filename)

def initialise_anomaly_window():
    """Start a new anomaly-summary window from the current counters."""
    global last_anomaly_summary_time
    last_anomaly_summary_time = local_now()
    anomaly_window.update({
        'capture_slow': 0,
        'cpu_hot': 0,
        'quality_warning': 0,
        'quality_critical': 0,
        'lens_degraded': 0,
        'exposure_limit': 0,
        'ftp_failures_start': ftp_failure_count,
        'camera_failures_start': camera_acquisition_failure_count,
        'storage_failures_start': storage_failure_count,
        'processing_failures_start': image_processing_failure_count,
        'telemetry_failures_start': telemetry_failure_count,
        'status_failures_start': status_failure_count,
        'timelapse_gaps': 0,
        'max_capture_ms': 0.0,
        'max_cpu_c': None,
    })

def record_capture_anomalies(measurement, processing_ms, cpu_temperature_c):
    """Accumulate lightweight anomaly counters from each completed capture."""
    anomaly_window['max_capture_ms'] = max(anomaly_window['max_capture_ms'], processing_ms)
    if processing_ms >= LOG_ANOMALY_CAPTURE_WARNING_MS:
        anomaly_window['capture_slow'] += 1
    if cpu_temperature_c is not None:
        previous = anomaly_window['max_cpu_c']
        anomaly_window['max_cpu_c'] = cpu_temperature_c if previous is None else max(previous, cpu_temperature_c)
        if cpu_temperature_c >= LOG_ANOMALY_CPU_WARNING_C:
            anomaly_window['cpu_hot'] += 1
    quality = measurement.get('image_quality_status')
    if quality == 'WARNING':
        anomaly_window['quality_warning'] += 1
    elif quality == 'CRITICAL':
        anomaly_window['quality_critical'] += 1
    if measurement.get('lens_status') in ('DEGRADED', 'POSSIBLE OBSTRUCTION'):
        anomaly_window['lens_degraded'] += 1
    if current_exposure_action == 'LIMIT REACHED':
        anomaly_window['exposure_limit'] += 1

def log_anomaly_summary(force=False):
    """Emit one compact health/anomaly summary for the current time window."""
    if not LOG_ANOMALY_SUMMARY_ENABLED:
        return
    now = local_now()
    if last_anomaly_summary_time is None:
        initialise_anomaly_window()
        return
    elapsed = now - last_anomaly_summary_time
    if not force and elapsed < timedelta(minutes=LOG_ANOMALY_SUMMARY_INTERVAL_MINUTES):
        return
    deltas = {
        'Camera': max(0, camera_acquisition_failure_count - anomaly_window['camera_failures_start']),
        'Storage': max(0, storage_failure_count - anomaly_window['storage_failures_start']),
        'Processing': max(0, image_processing_failure_count - anomaly_window['processing_failures_start']),
        'Telemetry': max(0, telemetry_failure_count - anomaly_window['telemetry_failures_start']),
        'Status': max(0, status_failure_count - anomaly_window['status_failures_start']),
        'FTP': max(0, ftp_failure_count - anomaly_window['ftp_failures_start']),
    }
    total = (anomaly_window['capture_slow'] + anomaly_window['cpu_hot'] +
             anomaly_window['quality_warning'] + anomaly_window['quality_critical'] +
             anomaly_window['lens_degraded'] + anomaly_window['exposure_limit'] +
             anomaly_window['timelapse_gaps']
             + deltas['Camera'] + deltas['Storage'] + deltas['Processing']
             + deltas['Telemetry'] + deltas['Status']
             + (deltas['FTP'] if deltas['FTP'] >= LOG_ANOMALY_FTP_FAILURE_WARNING else 0))
    max_cpu = anomaly_window['max_cpu_c']
    logger.info(
        '[ANOMALY SUMMARY] Window=%.0fmin | Total=%d | SlowCapture=%d | MaxProc=%.0fms | '
        'HotCPU=%d | MaxCPU=%sC | QualityWarn=%d | QualityCrit=%d | Lens=%d | '
        'ExposureLimit=%d | CameraFail=%d | StorageFail=%d | ProcessingFail=%d | '
        'TelemetryFail=%d | StatusFail=%d | FTPFail=%d | TimelapseGaps=%d',
        elapsed.total_seconds() / 60.0, total,
        anomaly_window['capture_slow'], anomaly_window['max_capture_ms'],
        anomaly_window['cpu_hot'], f'{max_cpu:.1f}' if max_cpu is not None else '--',
        anomaly_window['quality_warning'], anomaly_window['quality_critical'],
        anomaly_window['lens_degraded'], anomaly_window['exposure_limit'],
        deltas['Camera'], deltas['Storage'], deltas['Processing'], deltas['Telemetry'],
        deltas['Status'], deltas['FTP'], anomaly_window['timelapse_gaps'],
    )
    if total:
        audit_event('anomaly_summary', severity='WARNING', window_minutes=round(elapsed.total_seconds()/60.0, 1), total=total, slow_captures=anomaly_window['capture_slow'], max_capture_ms=round(anomaly_window['max_capture_ms'], 1), hot_cpu=anomaly_window['cpu_hot'], max_cpu_c=max_cpu, quality_warning=anomaly_window['quality_warning'], quality_critical=anomaly_window['quality_critical'], lens_degraded=anomaly_window['lens_degraded'], exposure_limit=anomaly_window['exposure_limit'], failures=deltas, timelapse_gaps=anomaly_window['timelapse_gaps'])
    initialise_anomaly_window()

def cleanup_old_files():
    frame_cutoff = (local_now() - timedelta(days=WEB_FRAME_RETENTION_DAYS)).timestamp()
    video_cutoff = (local_now() - timedelta(days=VIDEO_RETENTION_DAYS)).timestamp()
    summary_cutoff = (local_now() - timedelta(days=DAILY_SUMMARY_RETENTION_DAYS)).timestamp()
    for pattern, cutoff in ((os.path.join(FRAMES_PATH, 'frame_*.jpg'), frame_cutoff), (os.path.join(TIMELAPSE_PATH, 'timelapse_*.mp4'), video_cutoff), (os.path.join(LOGS_PATH, 'daily_summary_*.json'), summary_cutoff), (os.path.join(LOGS_PATH, 'daily_health_*.json'), summary_cutoff)):
        for filename in glob.glob(pattern):
            try:
                if os.path.getmtime(filename) < cutoff:
                    os.remove(filename)
            except OSError:
                logger.warning('[STORAGE] Could not process %s', filename)
    compress_previous_month_telemetry()
    cleanup_expired_telemetry()
    cleanup_old_audit_logs()
    cleanup_old_ftp_snapshots()
    cleanup_incomplete_timelapse_files()
    cleanup_old_hourly_segments()
    emergency_storage_cleanup()
    logger.info('[STORAGE] %.2f GB free', get_free_space_gb())

# V47.3 expanded system-health snapshot and persistent health history -----------
def _read_proc_status_kb(field):
    try:
        with open('/proc/self/status', 'r', encoding='ascii') as source:
            for line in source:
                if line.startswith(field + ':'):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None

def _read_meminfo_kb():
    values = {}
    try:
        with open('/proc/meminfo', 'r', encoding='ascii') as source:
            for line in source:
                key, sep, value = line.partition(':')
                if sep:
                    try:
                        values[key] = int(value.split()[0])
                    except (ValueError, IndexError):
                        pass
    except OSError:
        pass
    return values

def _read_host_uptime_seconds():
    try:
        with open('/proc/uptime', 'r', encoding='ascii') as source:
            return round(float(source.read().split()[0]), 1)
    except (OSError, ValueError, IndexError):
        return None

def _read_pi_throttled():
    try:
        result = subprocess.run(['vcgencmd', 'get_throttled'], capture_output=True, text=True, timeout=3)
        text = result.stdout.strip()
        if result.returncode == 0 and '=' in text:
            value = int(text.partition('=')[2], 16)
            return {'raw': text, 'value': value, 'throttled_now': bool(value & 0x4), 'under_voltage_now': bool(value & 0x1), 'frequency_capped_now': bool(value & 0x2), 'soft_temperature_limit_now': bool(value & 0x8), 'throttling_occurred': bool(value & 0x40000), 'under_voltage_occurred': bool(value & 0x10000), 'frequency_capping_occurred': bool(value & 0x20000), 'soft_temperature_limit_occurred': bool(value & 0x80000)}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return {'raw': None, 'value': None, 'throttled_now': None, 'under_voltage_now': None, 'frequency_capped_now': None, 'soft_temperature_limit_now': None, 'throttling_occurred': None, 'under_voltage_occurred': None, 'frequency_capping_occurred': None, 'soft_temperature_limit_occurred': None}

def collect_system_health_snapshot(now=None):
    """Collect a low-cost Raspberry Pi/process/storage health snapshot."""
    global health_previous_process_rss_bytes
    now = now or local_now()
    mem = _read_meminfo_kb()
    total_kb = mem.get('MemTotal')
    available_kb = mem.get('MemAvailable')
    used_kb = total_kb - available_kb if total_kb is not None and available_kb is not None else None
    memory_percent = round(used_kb * 100.0 / total_kb, 2) if total_kb and used_kb is not None else None
    rss_kb = _read_proc_status_kb('VmRSS')
    rss_bytes = rss_kb * 1024 if rss_kb is not None else None
    previous_rss = health_previous_process_rss_bytes
    rss_delta = rss_bytes - previous_rss if rss_bytes is not None and previous_rss is not None else None
    if rss_bytes is not None:
        health_previous_process_rss_bytes = rss_bytes
    disk = shutil.disk_usage(LOCAL_SAVE_PATH)
    disk_used_percent = round(disk.used * 100.0 / disk.total, 2) if disk.total else None
    cpu_temp = get_cpu_temperature_c()
    try:
        load1, load5, load15 = os.getloadavg()
    except (OSError, AttributeError):
        load1 = load5 = load15 = None
    try:
        cpu_count = os.cpu_count() or 1
        cpu_load_percent = round(float(load1) * 100.0 / cpu_count, 2) if load1 is not None else None
    except (TypeError, ValueError):
        cpu_load_percent = None
    process_uptime = max(0.0, (now - service_start_time).total_seconds())
    processing_average = capture_processing_total_ms / capture_count if capture_count else 0.0
    pi_throttle = _read_pi_throttled()
    reasons = []
    severity = 0
    def flag(level, reason):
        nonlocal severity
        severity = max(severity, level); reasons.append(reason)
    if cpu_temp is not None:
        if cpu_temp >= HEALTH_CPU_CRITICAL_C: flag(2, 'CPU temperature critical')
        elif cpu_temp >= HEALTH_CPU_WARNING_C: flag(1, 'CPU temperature high')
    if disk_used_percent is not None:
        if disk_used_percent >= HEALTH_DISK_CRITICAL_PERCENT: flag(2, 'Disk usage critical')
        elif disk_used_percent >= HEALTH_DISK_WARNING_PERCENT: flag(1, 'Disk usage high')
    if memory_percent is not None:
        if memory_percent >= HEALTH_MEMORY_CRITICAL_PERCENT: flag(2, 'Memory usage critical')
        elif memory_percent >= HEALTH_MEMORY_WARNING_PERCENT: flag(1, 'Memory usage high')
    if pi_throttle.get('throttled_now') or pi_throttle.get('under_voltage_now') or pi_throttle.get('frequency_capped_now') or pi_throttle.get('soft_temperature_limit_now'):
        flag(2, 'Raspberry Pi throttling active')
    if consecutive_camera_acquisition_failures: flag(2, 'Camera acquisition failures active')
    if globals().get('ftp_health_state') == 'OUTAGE': flag(2, 'FTP outage')
    elif globals().get('ftp_health_state') == 'DEGRADED': flag(1, 'FTP degraded')
    if globals().get('control_health') == 'UNHEALTHY': flag(2, 'Control unhealthy')
    elif globals().get('control_health') == 'DEGRADED': flag(1, 'Control degraded')
    overall = ('CRITICAL', 'WARNING', 'HEALTHY')[0] if False else ('CRITICAL' if severity == 2 else 'WARNING' if severity == 1 else 'HEALTHY')
    return {
        'schema_version': HEALTH_SCHEMA_VERSION, 'timestamp': now.isoformat(), 'release': VERSION,
        'telemetry_schema': TELEMETRY_SCHEMA_VERSION, 'overall_health': overall, 'health_reasons': reasons,
        'system': {'hostname': socket.gethostname(), 'cpu_temperature_c': cpu_temp, 'cpu_count': os.cpu_count(), 'cpu_load_percent': cpu_load_percent, 'load_1m': round(load1,3) if load1 is not None else None, 'load_5m': round(load5,3) if load5 is not None else None, 'load_15m': round(load15,3) if load15 is not None else None, 'host_uptime_seconds': _read_host_uptime_seconds(), 'pi_throttling': pi_throttle},
        'memory': {'total_bytes': total_kb*1024 if total_kb is not None else None, 'used_bytes': used_kb*1024 if used_kb is not None else None, 'available_bytes': available_kb*1024 if available_kb is not None else None, 'used_percent': memory_percent, 'process_rss_bytes': rss_bytes, 'process_rss_delta_bytes': rss_delta},
        'storage': {'path': LOCAL_SAVE_PATH, 'total_bytes': disk.total, 'used_bytes': disk.used, 'free_bytes': disk.free, 'used_percent': disk_used_percent, 'free_space_gb': round(disk.free/1024**3,2)},
        'service': {'process_uptime_seconds': round(process_uptime,1), 'camera_mode': current_camera_mode, 'capture_count': capture_count, 'last_capture_time': last_capture_time.isoformat() if last_capture_time else None, 'capture_processing_average_ms': round(processing_average,1), 'capture_processing_max_ms': round(capture_processing_max_ms,1), 'camera_acquisition_failures': camera_acquisition_failure_count, 'image_processing_failures': image_processing_failure_count, 'storage_failures': storage_failure_count, 'telemetry_failures': telemetry_failure_count, 'camera_restarts': camera_restart_count, 'ftp_health': globals().get('ftp_health_state'), 'control_health': globals().get('control_health'), 'control_ack_p95_captures': globals().get('control_ack_p95_captures',0)},
    }

def persist_system_health_snapshot(snapshot):
    """Append one V47.3 health record. Failure never interrupts capture."""
    directory = HEALTH_HISTORY_PATH
    filename = os.path.join(directory, 'health_' + local_now().strftime('%Y%m%d') + '.jsonl')
    try:
        os.makedirs(directory, exist_ok=True)
        with open(filename, 'a', encoding='utf-8') as output:
            output.write(json.dumps(snapshot, separators=(',', ':'), default=str) + '\n')
            output.flush(); os.fsync(output.fileno())
        return filename
    except OSError:
        logger.exception('[SYSTEM HEALTH] Persistent history write failed | File=%s', filename)
        return None

def log_system_health_snapshot(force=False):
    """Collect/log/persist system health at most once per configured interval."""
    global last_health_snapshot_time, health_snapshot_count, health_snapshot_failure_count
    now = local_now()
    if not force and last_health_snapshot_time is not None and now-last_health_snapshot_time < timedelta(minutes=HEALTH_SNAPSHOT_INTERVAL_MINUTES):
        return None
    try:
        snapshot = collect_system_health_snapshot(now)
        persisted = persist_system_health_snapshot(snapshot)
        if persisted is None:
            health_snapshot_failure_count += 1
        else:
            health_snapshot_count += 1
        last_health_snapshot_time = now
        system=snapshot['system']; memory=snapshot['memory']; storage=snapshot['storage']; service=snapshot['service']
        logger.info('[SYSTEM HEALTH] Overall=%s | CPU=%sC Load=%.2f/%.2f/%.2f | Mem=%s%% RSS=%.1fMB Delta=%s | Disk=%s%% Free=%.1fGB | Mode=%s | ProcAvg=%.0fms ProcMax=%.0fms | History=%s', snapshot['overall_health'], system['cpu_temperature_c'] if system['cpu_temperature_c'] is not None else '--', system['load_1m'] or 0.0, system['load_5m'] or 0.0, system['load_15m'] or 0.0, memory['used_percent'] if memory['used_percent'] is not None else '--', (memory['process_rss_bytes'] or 0)/1024**2, memory['process_rss_delta_bytes'] if memory['process_rss_delta_bytes'] is not None else '--', storage['used_percent'], storage['free_space_gb'], service['camera_mode'], service['capture_processing_average_ms'], service['capture_processing_max_ms'], persisted or 'FAILED')
        return snapshot
    except Exception:
        health_snapshot_failure_count += 1
        last_health_snapshot_time = now
        logger.exception('[SYSTEM HEALTH] Snapshot collection failed; capture service continues')
        return None

def cleanup_expired_health_history():
    cutoff = (local_now()-timedelta(days=HEALTH_HISTORY_RETENTION_DAYS)).timestamp()
    for filename in glob.glob(os.path.join(HEALTH_HISTORY_PATH, 'health_*.jsonl')):
        try:
            if os.path.getmtime(filename) < cutoff: os.remove(filename)
        except OSError:
            logger.exception('[SYSTEM HEALTH] Could not remove %s', filename)
