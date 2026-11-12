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
    filename = os.path.join(LOGS_PATH, f'daily_summary_{day:%Y%m%d}.json')
    baseline = daily_counter_baseline or {key: 0 for key in snapshot_counters()}
    current = snapshot_counters()
    daily = {key: current[key] - baseline.get(key, 0) for key in current}
    summary = {'date': day.isoformat(), **daily, 'free_space_gb': round(get_free_space_gb(), 2), 'timelapse_local_complete': os.path.exists(os.path.join(TIMELAPSE_PATH, f'timelapse_{day:%Y%m%d}.mp4')), 'timelapse_publish_complete': last_timelapse_completed_for == day, 'timelapse_build_method': last_timelapse_build_method, 'timelapse_segments': last_timelapse_segment_count, 'timelapse_expected_frames': last_timelapse_expected_frames, 'timelapse_source_gaps': last_timelapse_source_gaps}
    temporary = filename + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as output:
        json.dump(summary, output, indent=2)
    os.replace(temporary, filename)

def update_daily_summary_timelapse_status(day):
    """Update timelapse fields without recalculating daily counters."""
    filename = os.path.join(LOGS_PATH, f'daily_summary_{day:%Y%m%d}.json')
    try:
        with open(filename, 'r', encoding='utf-8') as source:
            summary = json.load(source)
    except FileNotFoundError:
        summary = {'date': day.isoformat()}
    except (OSError, ValueError, json.JSONDecodeError):
        logger.exception('[DAILY SUMMARY] Could not read %s', filename)
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
        logger.exception('[DAILY SUMMARY] Could not update timelapse status for %s', day)
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
    global last_anomaly_summary_time, anomaly_window
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
    global last_anomaly_summary_time
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
    for pattern, cutoff in ((os.path.join(FRAMES_PATH, 'frame_*.jpg'), frame_cutoff), (os.path.join(TIMELAPSE_PATH, 'timelapse_*.mp4'), video_cutoff), (os.path.join(LOGS_PATH, 'daily_summary_*.json'), summary_cutoff)):
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
