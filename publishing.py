"""V45-TL8-M2 physical module: publishing.py. Loaded into the shared runtime namespace.
Do not import directly; use weather_camera.py.
"""

def write_status_file(capture_time, metadata, measurement):
    now = local_now()

    gains = metadata.get('ColourGains', (0.0, 0.0))

    try:
        red_gain, blue_gain = (
            float(gains[0]),
            float(gains[1]),
        )

    except (TypeError, ValueError, IndexError):
        red_gain = blue_gain = 0.0

    status = {
        'station': STATION_NAME,
        'script_version': SCRIPT_VERSION,
        'capture_time': capture_time.isoformat(),

        'camera_healthy':
            consecutive_camera_acquisition_failures == 0,

        'camera_mode':
            current_camera_mode,

        'mode_transition_count':
            mode_transition_count,

        'mode_duration_seconds':
            round(
                (
                    local_now()
                    - mode_entered_time
                ).total_seconds(),
                1,
            )
            if mode_entered_time is not None
            else None,

        'mode_last_duration_seconds':
            round(mode_last_duration_seconds, 1)
            if mode_last_duration_seconds is not None
            else None,

        'solar_elevation':
            round(current_solar_elevation, 2),

        'uptime_seconds':
            round(
                (now - service_start_time).total_seconds(),
                1,
            ),

        'ftp_previous_upload_healthy':
            ftp_consecutive_failures == 0,

        'ftp_consecutive_failures':
            ftp_consecutive_failures,
        'ftp_health_state': ftp_health_state,
        'ftp_health_state_since': ftp_health_state_since.isoformat() if ftp_health_state_since else None,
        'ftp_outage_started': ftp_outage_started.isoformat() if ftp_outage_started else None,
        'ftp_outage_count': ftp_outage_count,
        'ftp_recovery_count': ftp_recovery_count,

        'ftp_worker_alive':
            ftp_thread is not None
            and ftp_thread.is_alive(),

        'ftp_worker_restart_count':
            ftp_worker_restart_count,

        'ftp_worker_unexpected_stops':
            ftp_worker_unexpected_stops,

        'ftp_worker_last_seen':
            (
                ftp_worker_last_seen.isoformat()
                if ftp_worker_last_seen is not None
                else None
            ),

        'ftp_worker_last_restart':
            (
                ftp_worker_last_restart.isoformat()
                if ftp_worker_last_restart is not None
                else None
            ),

        'ftp_last_success_time':
            ftp_last_success_time.isoformat()
            if ftp_last_success_time
            else None,    

        'capture_count':
            capture_count,

        'camera_acquisition_failure_count':
            camera_acquisition_failure_count,

        'image_processing_failure_count':
            image_processing_failure_count,

        'storage_failure_count':
            storage_failure_count,

        'telemetry_failure_count':
            telemetry_failure_count,

        'status_failure_count':
            status_failure_count,

        'camera_restart_count':
            camera_restart_count,

        'low_light_floor_armed':
            low_light_entry_floor_product is not None,

        'low_light_floor_product':
            round(low_light_entry_floor_product, 1)
            if low_light_entry_floor_product is not None
            else None,

        'low_light_floor_interventions':
            low_light_floor_interventions,

        'exposure_seconds':
            round(
                metadata.get('ExposureTime', 0)
                / 1000000,
                4,
            ),

        'analogue_gain':
            metadata.get('AnalogueGain'),

        'digital_gain':
            metadata.get('DigitalGain'),

        'brightness':
            round(measurement['brightness'], 1),

        'filtered_brightness':
            round(
                measurement.get(
                    'filtered_brightness',
                    measurement['brightness'],
                ),
                1,
            ),

        'contrast':
            round(measurement['contrast'], 1),

        'colour_gain_red':
            round(red_gain, 3),

        'colour_gain_blue':
            round(blue_gain, 3),

        'highlights_percent':
            round(measurement['highlights'], 2),

        'shadows_percent':
            round(measurement['shadows'], 2),

        'free_space_gb':
            round(get_free_space_gb(), 2),

        'cpu_temperature_c':
            get_cpu_temperature_c(),

        'sharpness_score':
            round(measurement['sharpness_score'], 3),

        'sharpness_baseline':
            round(
                measurement['sharpness_baseline'],
                3,
            )
            if measurement.get('sharpness_baseline')
            is not None
            else None,

        'sharpness_ratio':
            round(
                measurement['sharpness_ratio'],
                3,
            )
            if measurement['sharpness_ratio']
            is not None
            else None,

        'edge_density':
            round(measurement['edge_density'], 3),

        'image_quality_score':
            round(
                measurement['image_quality_score'],
                1,
            )
            if measurement['image_quality_score']
            is not None
            else None,

        'image_quality_status':
            measurement['image_quality_status'],

        'quality_learning_samples':
            measurement['quality_learning_samples'],

        'quality_learning_required':
            measurement['quality_learning_required'],

        'lens_status':
            measurement['lens_status'],

        'night_observability':
            measurement.get(
                'night_observability',
                'N/A',
            ),
    }

    # V49.9: publish additional controller observability while preserving telemetry-v4.
    midpoint = measurement.get('controller_target_brightness')
    current_samples = int(measurement.get('quality_learning_samples') or 0)
    required_samples = int(measurement.get('quality_learning_required') or 0)
    progress = 100.0 if required_samples <= 0 and measurement.get('image_quality_status') not in ('LEARNING','SETTLING') else (min(100.0, current_samples * 100.0 / required_samples) if required_samples else 0.0)
    learning_state = 'LEARNING' if measurement.get('image_quality_status') in ('LEARNING','SETTLING') else 'STABLE'
    status.update({
        'controller_decision': measurement.get('controller_decision', 'HOLD_STABLE'),
        'controller_target_brightness': round(midpoint, 2) if midpoint is not None else None,
        'controller_error': round(measurement.get('controller_error'), 2) if measurement.get('controller_error') is not None else None,
        'controller_deadband': measurement.get('controller_deadband'),
        'controller_delta_ms': round(measurement.get('controller_delta_ms'), 3) if measurement.get('controller_delta_ms') is not None else None,
        'controller_delta_pct': round(measurement.get('controller_delta_pct'), 2) if measurement.get('controller_delta_pct') is not None else None,
        'controller_clamped_by': measurement.get('controller_clamped_by'),
        'controller_next_exposure_ms': round(measurement.get('controller_next_exposure_ms'), 3) if measurement.get('controller_next_exposure_ms') is not None else None,
        'learning_state': learning_state, 'learning_mode': current_camera_mode,
        'learning_samples_current': current_samples, 'learning_samples_required': required_samples,
        'learning_progress_pct': round(progress, 1),
        'software_version': VERSION, 'telemetry_schema_version': TELEMETRY_SCHEMA_VERSION,
    })
    # Existing V47/V49.8.1 control-health fields remain authoritative.
    status.update(control_status_fields(capture_time))
    try:
        obs = {k: status.get(k) for k in (
            'capture_time','software_version','telemetry_schema_version','camera_mode','control_health',
            'controller_decision','controller_target_brightness','controller_error','controller_deadband',
            'controller_delta_ms','controller_delta_pct','controller_clamped_by','controller_next_exposure_ms',
            'controller_at_exposure_limit','controller_at_gain_limit','learning_state','learning_mode',
            'learning_samples_current','learning_samples_required','learning_progress_pct')}
        obs_file=os.path.join(LOGS_PATH,'controller_observability.json')
        tmp=obs_file+'.tmp'
        with open(tmp,'w',encoding='utf-8') as f: json.dump(obs,f,indent=2,sort_keys=True)
        os.replace(tmp,obs_file)
    except OSError:
        logger.exception('[V49.9] Could not write controller observability')

    filename = os.path.join(
        LOGS_PATH,
        'camera_status.json',
    )

    temporary = filename + '.tmp'

    with open(
        temporary,
        'w',
        encoding='utf-8',
    ) as output:
        json.dump(status, output, indent=2)

    os.replace(temporary, filename)

    return filename

TELEMETRY_FIELDS = ['capture_time', 'camera_mode', 'solar_elevation_deg', 'exposure_ms', 'analogue_gain', 'digital_gain', 'colour_gain_red', 'colour_gain_blue', 'brightness_raw', 'brightness_filtered', 'target_low', 'target_high', 'brightness_deadband', 'sky_brightness', 'horizon_brightness', 'foreground_brightness', 'contrast', 'highlights_percent', 'shadows_percent', 'free_space_gb', 'next_exposure_ms', 'next_analogue_gain', 'exposure_action', 'awb_sample_count', 'capture_processing_ms', 'capture_count', 'sharpness_score', 'sharpness_baseline', 'sharpness_ratio', 'edge_density', 'image_quality_score', 'image_quality_status', 'quality_learning_samples', 'quality_learning_required', 'lens_status', 'night_observability', 'cpu_temperature_c', 'controller_at_exposure_limit', 'controller_at_gain_limit', 'mode_transition_count', 'low_light_floor_interventions', 'ftp_consecutive_failures', 'control_id', 'control_ack_state', 'control_ack_capture_count', 'control_ack_latency_seconds', 'control_exposure_acknowledged', 'control_gain_acknowledged', 'control_matched_history_depth', 'control_pending_age_seconds', 'control_superseded_count', 'control_pipeline_lag_count', 'control_timeout_count', 'control_reconciliation_count', 'control_health', 'control_ack_p95_captures', 'ffmpeg_active', 'ffmpeg_job_type']

def validate_v50_telemetry_row(row, capture_time):
    """Validate a row before it mutates the immutable telemetry contract."""
    if set(row.keys()) != set(TELEMETRY_FIELDS):
        raise ValueError('telemetry row fields do not match the 58-field contract')
    captured = datetime.fromisoformat(str(row['capture_time']))
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=HARPENDEN_TIMEZONE)
    skew = abs((captured.astimezone(UTC_TIMEZONE) - capture_time.astimezone(UTC_TIMEZONE)).total_seconds())
    if skew > V50_TELEMETRY_MAX_CLOCK_SKEW_SECONDS:
        raise ValueError(f'telemetry capture time clock skew: {skew:.1f}s')
    if row['camera_mode'] not in ('DAY', 'TWILIGHT', 'LOW LIGHT', 'NIGHT'):
        raise ValueError(f"invalid camera mode: {row['camera_mode']}")

def get_monthly_telemetry_filename(capture_time):
    """Return the explicit versioned monthly telemetry filename."""
    return os.path.join(
        LOGS_PATH,
        f"{TELEMETRY_FILENAME_PREFIX}_v{TELEMETRY_SCHEMA_VERSION}_{capture_time.strftime('%Y%m')}.csv",
    )

def get_schema_safe_telemetry_filename(capture_time):
    """Return the vN monthly file only when its header matches this declared schema."""
    month_key = f"v{TELEMETRY_SCHEMA_VERSION}_{capture_time.strftime('%Y%m')}"
    cached = telemetry_schema_filename_cache.get(month_key)
    if cached:
        return cached
    filename = get_monthly_telemetry_filename(capture_time)
    if os.path.exists(filename) and os.path.getsize(filename) > 0:
        try:
            with open(filename, 'r', newline='', encoding='utf-8') as source:
                existing_fields = next(csv.reader(source), [])
        except (OSError, csv.Error):
            logger.exception('[TELEMETRY] Could not inspect schema for %s', filename)
            return None
        if existing_fields != TELEMETRY_FIELDS:
            logger.error(
                '[TELEMETRY] Explicit schema mismatch | Version=v%d | Existing=%d | Required=%d | File=%s',
                TELEMETRY_SCHEMA_VERSION, len(existing_fields), len(TELEMETRY_FIELDS), filename,
            )
            return None
    telemetry_schema_filename_cache[month_key] = filename
    return filename

def append_monthly_telemetry(capture_time, metadata, measurement, processing_ms):
    """Append the completed capture and controller outcome to monthly telemetry."""
    filename = get_schema_safe_telemetry_filename(capture_time)
    if filename is None:
        logger.error('[TELEMETRY] Row not written because explicit schema validation failed')
        return None
    gains = metadata.get('ColourGains', (0.0, 0.0))
    try:
        red_gain, blue_gain = (float(gains[0]), float(gains[1]))
    except (TypeError, ValueError, IndexError):
        red_gain = blue_gain = 0.0
    if current_camera_mode == 'DAY':
        next_exposure_ms, next_analogue_gain, exposure_action = ('', '', 'AUTO')
        at_exposure_limit = at_gain_limit = False
    else:
        next_exposure_ms = round((manual_exposure_us or 0) / 1000.0, 3)
        next_analogue_gain = round(float(manual_gain or 0.0), 3)
        exposure_action = current_exposure_action
        at_exposure_limit = (manual_exposure_us or 0) >= maximum_exposure_for_mode(current_camera_mode) - 50000
        at_gain_limit = (manual_gain or 0.0) >= ABSOLUTE_MAX_GAIN - 0.01
    row = {'capture_time': capture_time.isoformat(), 'camera_mode': current_camera_mode, 'solar_elevation_deg': round(current_solar_elevation, 3), 'exposure_ms': round(metadata.get('ExposureTime', 0) / 1000.0, 3), 'analogue_gain': round(float(metadata.get('AnalogueGain', 0.0)), 3), 'digital_gain': round(float(metadata.get('DigitalGain', 1.0)), 3), 'colour_gain_red': round(red_gain, 3), 'colour_gain_blue': round(blue_gain, 3), 'brightness_raw': round(measurement['brightness'], 2), 'brightness_filtered': round(measurement.get('filtered_brightness', measurement['brightness']), 2), 'target_low': measurement.get('target_low', ''), 'target_high': measurement.get('target_high', ''), 'brightness_deadband': measurement.get('brightness_deadband', ''), 'sky_brightness': round(measurement['sky'], 2), 'horizon_brightness': round(measurement['horizon'], 2), 'foreground_brightness': round(measurement['foreground'], 2), 'contrast': round(measurement['contrast'], 2), 'highlights_percent': round(measurement['highlights'], 3), 'shadows_percent': round(measurement['shadows'], 3), 'free_space_gb': round(get_free_space_gb(), 3), 'next_exposure_ms': next_exposure_ms, 'next_analogue_gain': next_analogue_gain, 'exposure_action': exposure_action, 'awb_sample_count': len(awb_gain_history), 'capture_processing_ms': round(processing_ms, 3), 'capture_count': capture_count, 'sharpness_score': round(measurement['sharpness_score'], 3), 'sharpness_baseline': round(measurement['sharpness_baseline'], 3) if measurement.get('sharpness_baseline') is not None else '', 'sharpness_ratio': round(measurement['sharpness_ratio'], 3) if measurement['sharpness_ratio'] is not None else '', 'edge_density': round(measurement['edge_density'], 3), 'image_quality_score': round(measurement['image_quality_score'], 1) if measurement['image_quality_score'] is not None else '', 'image_quality_status': measurement['image_quality_status'], 'quality_learning_samples': measurement['quality_learning_samples'], 'quality_learning_required': measurement['quality_learning_required'], 'lens_status': measurement['lens_status'], 'night_observability': measurement.get('night_observability', 'N/A'), 'cpu_temperature_c': get_cpu_temperature_c(), 'controller_at_exposure_limit': at_exposure_limit, 'controller_at_gain_limit': at_gain_limit, 'mode_transition_count': mode_transition_count, 'low_light_floor_interventions': low_light_floor_interventions,'ftp_consecutive_failures': ftp_consecutive_failures, 'control_id': control_history[-1]['id'] if control_history else '', 'control_ack_state': control_ack_state, 'control_ack_capture_count': control_history[-1]['capture_count'] if control_history else 0, 'control_ack_latency_seconds': control_last_ack_latency_seconds if control_last_ack_latency_seconds is not None else '', 'control_exposure_acknowledged': control_exposure_acknowledged, 'control_gain_acknowledged': control_gain_acknowledged, 'control_matched_history_depth': control_matched_history_depth if control_matched_history_depth is not None else '', 'control_pending_age_seconds': control_status_fields(capture_time)['control_pending_age_seconds'], 'control_superseded_count': control_superseded_count, 'control_pipeline_lag_count': control_pipeline_lag_count, 'control_timeout_count': control_timeout_count, 'control_reconciliation_count': control_reconciliation_count, 'control_health': control_health, 'control_ack_p95_captures': control_ack_p95_captures, 'ffmpeg_active': globals().get('ffmpeg_active', False), 'ffmpeg_job_type': globals().get('ffmpeg_job_type') or ''}
    try:
        validate_v50_telemetry_row(row, capture_time)
    except (TypeError, ValueError) as error:
        logger.error('[TELEMETRY] V50 validation failed: %s', error)
        audit_event('telemetry_validation_failure', severity='ERROR', reason=str(error))
        return None
    with telemetry_lock:
        new_file = not os.path.exists(filename) or os.path.getsize(filename) == 0
        try:
            with open(filename, 'a', newline='', encoding='utf-8') as output:
                writer = csv.DictWriter(output, fieldnames=TELEMETRY_FIELDS)
                if new_file:
                    writer.writeheader()
                writer.writerow(row)
                if TELEMETRY_FLUSH_EACH_ROW:
                    output.flush()
                    os.fsync(output.fileno())
        except OSError:
            logger.exception('[TELEMETRY] Failed to append %s', filename)
            return None
    return filename

def connect_to_ftp():
    ftp = ftplib.FTP(timeout=FTP_TIMEOUT_SECONDS)
    ftp.connect(FTP_SERVER)
    ftp.login(FTP_USERNAME, FTP_PASSWORD)
    ftp.cwd(FTP_UPLOAD_PATH)
    return ftp

def upload_to_ftp(local_filename, remote_filename, allow_shutdown=False):
    """Upload atomically via a temporary remote name, retrying transient errors."""
    temporary_remote = remote_filename + '.uploading'
    for attempt in range(1, FTP_MAX_RETRIES + 1):
        if shutdown_event.is_set() and (not allow_shutdown):
            return False
        try:
            with connect_to_ftp() as ftp:
                try:
                    ftp.delete(temporary_remote)
                except ftplib.error_perm:
                    pass
                with open(local_filename, 'rb') as file_handle:
                    ftp.storbinary('STOR ' + temporary_remote, file_handle, blocksize=262144)
                try:
                    ftp.delete(remote_filename)
                except ftplib.error_perm:
                    pass
                ftp.rename(temporary_remote, remote_filename)
            return True
        except ftplib.all_errors + (OSError,) as error:
            logger.info('[FTP RETRY] Attempt %d/%d failed for %s: %s', attempt, FTP_MAX_RETRIES, remote_filename, error)
            if attempt < FTP_MAX_RETRIES and shutdown_event.wait(FTP_RETRY_DELAY_SECONDS):
                return False
    return False

def remove_upload_snapshot(item):
    for filename in item:
        try:
            os.remove(filename)
        except OSError:
            pass

def cleanup_old_ftp_snapshots():
    """Remove abandoned FTP staging files from earlier unclean shutdowns."""
    cutoff = (local_now() - timedelta(hours=FTP_SNAPSHOT_RETENTION_HOURS)).timestamp()
    removed = 0
    for pattern in (os.path.join(FTP_SNAPSHOT_PATH, 'image_*.jpg'), os.path.join(FTP_SNAPSHOT_PATH, 'status_*.json')):
        for filename in glob.glob(pattern):
            try:
                if os.path.getmtime(filename) < cutoff:
                    os.remove(filename)
                    removed += 1
            except FileNotFoundError:
                pass
            except OSError:
                logger.exception('[FTP SNAPSHOT] Could not remove %s', filename)
    if removed:
        logger.info('[FTP SNAPSHOT] Removed %d abandoned file(s)', removed)
        audit_event('ftp_snapshot_cleanup', removed_files=removed)
    return removed

def queue_live_upload(image_filename, status_filename, capture_time):
    """Queue immutable matching image/status snapshots, dropping stale work."""
    snapshot_id = capture_time.strftime('%Y%m%d_%H%M%S_%f')
    image_snapshot = os.path.join(FTP_SNAPSHOT_PATH, f'image_{snapshot_id}.jpg')
    status_snapshot = os.path.join(FTP_SNAPSHOT_PATH, f'status_{snapshot_id}.json')
    shutil.copyfile(image_filename, image_snapshot)
    shutil.copyfile(status_filename, status_snapshot)
    while True:
        try:
            stale = web_upload_queue.get_nowait()
            remove_upload_snapshot(stale)
            web_upload_queue.task_done()
        except queue.Empty:
            break
    try:
        web_upload_queue.put_nowait((image_snapshot, status_snapshot))
    except queue.Full:
        remove_upload_snapshot((image_snapshot, status_snapshot))

def ftp_worker():

    global ftp_image_success_count
    global ftp_status_success_count
    global ftp_failure_count
    global ftp_consecutive_failures
    global ftp_last_success_time
    global ftp_last_upload_ms
    global ftp_worker_last_seen

    while not shutdown_event.is_set() or not web_upload_queue.empty():

        ftp_worker_last_seen = local_now()

        image_filename = None
        status_filename = None

        try:

            try:

                image_filename, status_filename = (
                    web_upload_queue.get(timeout=1)
                )

            except queue.Empty:
                continue

            started = time.monotonic()

            try:

                image_ok = upload_to_ftp(
                    image_filename,
                    LATEST_IMAGE_REMOTE_FILENAME,
                    allow_shutdown=True,
                )

                status_ok = upload_to_ftp(
                    status_filename,
                    LATEST_STATUS_REMOTE_FILENAME,
                    allow_shutdown=True,
                )

                ftp_last_upload_ms = (
                    time.monotonic() - started
                ) * 1000.0

                ftp_image_success_count += int(image_ok)
                ftp_status_success_count += int(status_ok)

                if image_ok and status_ok:

                    if ftp_consecutive_failures > 0:

                        logger.info(
                            '[FTP] RECOVERED | PreviousFailures=%d',
                            ftp_consecutive_failures,
                        )

                        audit_event(
                            'ftp_recovered',
                            failures=ftp_consecutive_failures,
                        )

                    ftp_consecutive_failures = 0
                    ftp_last_success_time = local_now()
                    record_ftp_health_success()

                else:

                    ftp_failure_count += 1
                    ftp_consecutive_failures += 1
                    record_ftp_health_failure('live upload failed')

            except Exception:

                ftp_failure_count += 1
                ftp_consecutive_failures += 1
                record_ftp_health_failure('worker exception')

                logger.exception(
                    '[FTP WORKER] Unexpected processing error'
                )

                try:

                    audit_event(
                        'ftp_worker_processing_error',
                        severity='ERROR',
                    )

                except Exception:

                    logger.exception(
                        '[FTP WORKER] Audit logging failed'
                    )
                
        finally:

            ftp_worker_last_seen = local_now()

            if image_filename is not None:

                remove_upload_snapshot(
                    (
                        image_filename,
                        status_filename,
                    )
                )

                web_upload_queue.task_done()

# V47.2 FTP health lifecycle -------------------------------------------------
def set_ftp_health_state(new_state, reason=None):
    """Transition FTP health and emit one lifecycle event per state change."""
    global ftp_health_state, ftp_health_state_since, ftp_outage_started
    global ftp_outage_count, ftp_recovery_count, ftp_recovery_successes
    now = local_now()
    if new_state == ftp_health_state:
        return False
    previous = ftp_health_state
    duration = (now - ftp_health_state_since).total_seconds() if ftp_health_state_since else 0.0
    if new_state == 'OUTAGE':
        ftp_outage_started = now; ftp_outage_count += 1
    if previous == 'OUTAGE' and new_state == 'RECOVERING':
        ftp_recovery_count += 1
    if new_state == 'HEALTHY':
        outage_duration = (now - ftp_outage_started).total_seconds() if ftp_outage_started else 0.0
        logger.info('[FTP HEALTH] HEALTHY | Previous=%s | PreviousDuration=%.0fs | OutageDuration=%.0fs', previous, duration, outage_duration)
        ftp_outage_started = None; ftp_recovery_successes = 0
    elif new_state == 'DEGRADED':
        logger.warning('[FTP HEALTH] DEGRADED | Previous=%s | Failures=%d | Reason=%s', previous, ftp_consecutive_failures, reason or '--')
    elif new_state == 'OUTAGE':
        logger.error('[FTP HEALTH] OUTAGE | Failures=%d | Started=%s | Reason=%s', ftp_consecutive_failures, now.isoformat(), reason or '--')
    elif new_state == 'RECOVERING':
        logger.info('[FTP HEALTH] RECOVERING | ConsecutiveSuccesses=%d/%d', ftp_recovery_successes, FTP_HEALTH_RECOVERY_SUCCESSES)
    ftp_health_state = new_state; ftp_health_state_since = now
    audit_event('ftp_health_state', severity='ERROR' if new_state == 'OUTAGE' else ('WARNING' if new_state == 'DEGRADED' else 'INFO'), previous=previous, state=new_state, reason=reason, consecutive_failures=ftp_consecutive_failures)
    return True

def record_ftp_health_failure(reason):
    """Classify failed FTP batches while suppressing repetitive per-attempt noise."""
    global ftp_last_failure_log_time, ftp_suppressed_warning_count, ftp_recovery_successes
    now = local_now(); ftp_recovery_successes = 0
    if ftp_health_state == 'HEALTHY': set_ftp_health_state('DEGRADED', reason)
    if ftp_consecutive_failures >= FTP_HEALTH_OUTAGE_FAILURES: set_ftp_health_state('OUTAGE', reason)
    if ftp_last_failure_log_time is None or (now-ftp_last_failure_log_time).total_seconds() >= FTP_HEALTH_LOG_SUPPRESSION_SECONDS:
        logger.warning('[FTP FAILURE] State=%s | Consecutive=%d | Suppressed=%d | Reason=%s', ftp_health_state, ftp_consecutive_failures, ftp_suppressed_warning_count, reason)
        ftp_last_failure_log_time=now; ftp_suppressed_warning_count=0
    else:
        ftp_suppressed_warning_count += 1

def record_ftp_health_success():
    global ftp_recovery_successes
    if ftp_health_state in ('OUTAGE','DEGRADED'):
        ftp_recovery_successes += 1
        if ftp_health_state == 'OUTAGE': set_ftp_health_state('RECOVERING')
    elif ftp_health_state == 'RECOVERING':
        ftp_recovery_successes += 1
    if ftp_health_state in ('RECOVERING','DEGRADED') and ftp_recovery_successes >= FTP_HEALTH_RECOVERY_SUCCESSES:
        set_ftp_health_state('HEALTHY')
