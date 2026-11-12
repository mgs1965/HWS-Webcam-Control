"""V45-TL8-M2 physical module: runtime.py. Loaded into the shared runtime namespace.
Do not import directly; use weather_camera.py.
"""


def handle_termination_signal(signum, _frame):
    global termination_signal
    termination_signal = signum
    shutdown_event.set()

def install_signal_handlers():
    signal.signal(signal.SIGTERM, handle_termination_signal)
    signal.signal(signal.SIGINT, handle_termination_signal)

def sleep_until_next_capture():
    now_timestamp = time.time()
    next_timestamp = (math.floor(now_timestamp / CAPTURE_INTERVAL_SECONDS) + 1) * CAPTURE_INTERVAL_SECONDS
    shutdown_event.wait(max(0.0, next_timestamp - now_timestamp))

def ensure_ftp_worker_running():
    global ftp_thread
    global ftp_worker_restart_count
    global ftp_worker_unexpected_stops

    if ftp_thread is None:
        return

    if ftp_thread.is_alive():
        return

    ftp_worker_unexpected_stops += 1
    ftp_worker_restart_count += 1

    logger.error(
        '[FTP WORKER] Unexpected stop detected. Restarting worker.'
    )

    audit_event(
        'ftp_worker_restarted',
        severity='ERROR',
        restart_count=ftp_worker_restart_count,
    )

    ftp_thread = threading.Thread(
        target=ftp_worker,
        daemon=True,
        name='ftp-worker',
    )

    ftp_thread.start()

def main():
    """Start workers and camera, then run the clock-aligned capture service loop."""
    global current_operating_date, consecutive_camera_acquisition_failures, last_housekeeping_time
    global camera_acquisition_failure_count, image_processing_failure_count
    global storage_failure_count, last_daily_summary_date, ftp_thread
    global daily_counter_baseline
    install_signal_handlers()
    validate_storage_paths()
    logger.info('============================================================')
    logger.info(' HARPENDEN WEATHER STATION STARTING | %s %s', VERSION_DATE, VERSION)
    logger.info('[VERSION] Release=%s | TelemetrySchema=v%d', VERSION, TELEMETRY_SCHEMA_VERSION)
    logger.info('[STARTUP] Python=%s', platform.python_version())
    logger.info('[STARTUP] Host=%s', socket.gethostname())
    logger.info('[STARTUP] PID=%d', os.getpid())
    logger.info('[STARTUP] Started=%s', service_start_time.isoformat())
    logger.info('[LOGGING] Level=%s | INFO=%s | DEBUG=%s', logging.getLevelName(LOG_LEVEL), LOG_INFO_ENABLED, LOG_DEBUG_ENABLED)
    logger.info('============================================================')
    logger.info('[CONFIG] Capture=%ds TwilightTarget=%.1f-%.1f LowLightTarget=%.1f-%.1f NightTarget=%.1f-%.1f', CAPTURE_INTERVAL_SECONDS, TWILIGHT_TARGET_LOW, TWILIGHT_TARGET_HIGH, LOW_LIGHT_TARGET_LOW, LOW_LIGHT_TARGET_HIGH, NIGHT_TARGET_LOW, NIGHT_TARGET_HIGH)
    logger.info('[CONFIG] NightObservability B>=%.1f C>=%.1f ED>=%.2f SR>=%.2f Recovery=%d Failure=%d captures', NIGHT_OBSERVABILITY_MIN_BRIGHTNESS, NIGHT_OBSERVABILITY_MIN_CONTRAST, NIGHT_OBSERVABILITY_MIN_EDGE_DENSITY, NIGHT_OBSERVABILITY_MIN_SHARPNESS_RATIO, NIGHT_OBSERVABILITY_RECOVERY_CAPTURES, NIGHT_OBSERVABILITY_FAILURE_CAPTURES)
    logger.info('[CONFIG] LowLightMaxExposure=%.0fms | TimelapseCompleteness=%.0f%% | FTPAnomalyThreshold=%d', MAX_LOW_LIGHT_EXPOSURE_US / 1000.0, TIMELAPSE_MIN_FRAME_COMPLETENESS * 100.0, LOG_ANOMALY_FTP_FAILURE_WARNING)
    logger.info('[FTP SNAPSHOT] Staging=%s | StaleAfter=%dh', FTP_SNAPSHOT_PATH, FTP_SNAPSHOT_RETENTION_HOURS)
    audit_event('service_start', version=SCRIPT_VERSION, sensor=f'{SENSOR_WIDTH}x{SENSOR_HEIGHT}', output=f'{WEB_WIDTH}x{WEB_HEIGHT}')
    ftp_thread = threading.Thread(target=ftp_worker, daemon=True, name='ftp-worker')
    ftp_thread.start()
    try:
        with camera_lock:
            picam2.start()
        shutdown_event.wait(2)
        current_operating_date = local_now().date()
        last_daily_summary_date = current_operating_date
        daily_counter_baseline = snapshot_counters()
        load_controller_state()
        load_quality_state()
        get_harpenden_sun_times()
        configure_camera_mode(force=True)
        shutdown_event.wait(CAMERA_MODE_SETTLE_SECONDS)
        cleanup_old_files()
        last_housekeeping_time = local_now()
        initialise_anomaly_window()
        while not shutdown_event.is_set():
            sleep_until_next_capture()
            ensure_ftp_worker_running()
            if shutdown_event.is_set():
                break
            cycle_started = time.monotonic()
            try:
                check_for_new_day()
                schedule_timelapse()
                schedule_hourly_today_timelapse()
                image_filename, status_filename, capture_time = capture_frame()
                consecutive_camera_acquisition_failures = 0
                if status_filename:
                    queue_live_upload(image_filename, status_filename, capture_time)
            except CameraAcquisitionError:
                consecutive_camera_acquisition_failures += 1
                camera_acquisition_failure_count += 1
                logger.exception('[CAMERA] Acquisition failure %d/%d', consecutive_camera_acquisition_failures, MAX_CONSECUTIVE_CAPTURE_FAILURES)
                if consecutive_camera_acquisition_failures >= MAX_CONSECUTIVE_CAPTURE_FAILURES:
                    restart_camera()
                    consecutive_camera_acquisition_failures = 0
            except OSError:
                storage_failure_count += 1
                logger.exception('[STORAGE] Capture-cycle storage failure')
                audit_event('capture_storage_failure', severity='ERROR')
            except Exception:
                image_processing_failure_count += 1
                logger.exception('[PROCESSING] Capture-cycle processing failure')
                audit_event('capture_processing_failure', severity='ERROR')
            now = local_now()
            if last_daily_summary_date and now.date() != last_daily_summary_date:
                write_daily_health_summary(last_daily_summary_date)
                daily_counter_baseline = snapshot_counters()
                last_daily_summary_date = now.date()
            if now - last_housekeeping_time >= timedelta(hours=HOUSEKEEPING_INTERVAL_HOURS):
                cleanup_old_files()
                last_housekeeping_time = now
            log_anomaly_summary()
            elapsed = time.monotonic() - cycle_started
            if elapsed >= CAPTURE_INTERVAL_SECONDS:
                logger.warning('[TIMING] Cycle %.2f sec; next clock boundary will be used', elapsed)
    except KeyboardInterrupt:
        shutdown_event.set()
    finally:
        save_controller_state(force=True)
        log_anomaly_summary(force=True)
        shutdown_event.set()
        logger.info('[SYSTEM] Stopping camera; signal=%s', termination_signal)
        if ftp_thread and ftp_thread.is_alive():
            ftp_thread.join(timeout=FTP_WORKER_SHUTDOWN_TIMEOUT_SECONDS)
        try:
            with camera_lock:
                picam2.stop()
        except Exception:
            logger.exception('[SYSTEM] Camera stop failed')
        audit_event('service_stopped', signal=termination_signal)
        logger.info('[SYSTEM] Weather station stopped')
        logging.shutdown()
