"""V45-TL8-M2 physical module: state.py. Loaded into the shared runtime namespace.
Do not import directly; use weather_camera.py.
"""


def snapshot_counters():
    return {'capture_count': capture_count, 'camera_acquisition_failures': camera_acquisition_failure_count, 'image_processing_failures': image_processing_failure_count, 'storage_failures': storage_failure_count, 'telemetry_failures': telemetry_failure_count, 'status_failures': status_failure_count, 'camera_restarts': camera_restart_count, 'ftp_failures': ftp_failure_count}

def get_audit_log_filename(event_time=None):
    event_time = event_time or local_now()
    return os.path.join(LOGS_PATH, f"{AUDIT_LOG_FILENAME_PREFIX}_{event_time.strftime('%Y%m%d')}.jsonl")

def audit_event(event_type, severity='INFO', **details):
    """Append one structured JSONL operational event to the daily audit log."""
    record = {'timestamp': local_now().isoformat(), 'event_type': str(event_type), 'severity': str(severity).upper(), 'camera_mode': current_camera_mode, 'solar_elevation_deg': round(current_solar_elevation, 3) if current_solar_elevation is not None else None, 'details': details}
    filename = get_audit_log_filename()
    try:
        with audit_lock, open(filename, 'a', encoding='utf-8') as output:
            output.write(json.dumps(record, separators=(',', ':'), default=str) + '\n')
            output.flush()
            if AUDIT_FSYNC_EACH_EVENT:
                os.fsync(output.fileno())
    except OSError:
        logger.exception('[AUDIT] Failed to append %s', filename)

def cleanup_old_audit_logs():
    cutoff = (local_now() - timedelta(days=AUDIT_LOG_RETENTION_DAYS)).timestamp()
    for filename in glob.glob(os.path.join(LOGS_PATH, f'{AUDIT_LOG_FILENAME_PREFIX}_*.jsonl')):
        try:
            if os.path.getmtime(filename) < cutoff:
                os.remove(filename)
        except OSError:
            logger.exception('[AUDIT] Could not remove %s', filename)

def save_quality_state():
    """Atomically persist mode-specific rolling sharpness histories."""
    state = {'schema_version': QUALITY_STATE_SCHEMA_VERSION, 'saved': local_now().isoformat(), 'sharpness_history': {mode: [float(value) for value in history] for mode, history in sharpness_history.items()}}
    temporary = QUALITY_STATE_FILENAME + '.tmp'
    try:
        with open(temporary, 'w', encoding='utf-8') as output:
            json.dump(state, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, QUALITY_STATE_FILENAME)
    except OSError:
        logger.exception('[QUALITY STATE] Failed to save quality state')

def load_quality_state():
    """Restore quality histories when the saved state is no more than 7 days old."""
    try:
        with open(QUALITY_STATE_FILENAME, 'r', encoding='utf-8') as source:
            state = json.load(source)
        saved = datetime.fromisoformat(state['saved'])
        if saved.tzinfo is None:
            saved = saved.replace(tzinfo=HARPENDEN_TIMEZONE)
        age = local_now() - saved.astimezone(HARPENDEN_TIMEZONE)
        if age < timedelta(0) or age > timedelta(days=QUALITY_STATE_MAX_AGE_DAYS):
            logger.info('[QUALITY STATE] Saved histories are stale; relearning')
            return False
        restored = 0
        state_schema = int(state.get('schema_version', 1))
        values_by_mode = state.get('sharpness_history', {})
        for mode, history in sharpness_history.items():
            history.clear()
            if mode == 'NIGHT' and state_schema < QUALITY_STATE_SCHEMA_VERSION:
                logger.info('[QUALITY STATE] NIGHT history reset for schema migration %d -> %d', state_schema, QUALITY_STATE_SCHEMA_VERSION)
                continue
            for value in values_by_mode.get(mode, []):
                try:
                    value = float(value)
                    if math.isfinite(value) and value >= 0:
                        history.append(value)
                except (TypeError, ValueError):
                    continue
            restored += len(history)
            logger.info('[QUALITY STATE] %s restored %d sample(s)', mode, len(history))
        return restored > 0
    except FileNotFoundError:
        return False
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        logger.exception('[QUALITY STATE] Could not restore quality state')
        return False

def save_controller_state(force=False):
    """Atomically persist recent manual-controller and learned-AWB state."""
    global last_controller_state_save_time
    now = local_now()
    if not force and last_controller_state_save_time is not None and (now - last_controller_state_save_time < timedelta(minutes=CONTROLLER_STATE_SAVE_INTERVAL_MINUTES)):
        return
    state = {'saved': now.isoformat(), 'manual_exposure_us': manual_exposure_us, 'manual_gain': manual_gain, 'filtered_brightness': filtered_brightness, 'night_colour_gains': list(night_colour_gains) if night_colour_gains else None, 'awb_gain_history': [[float(r), float(b)] for r, b in awb_gain_history], 'camera_mode': current_camera_mode, 'last_timelapse_completed_for': last_timelapse_completed_for.isoformat() if last_timelapse_completed_for else None}
    temporary = CONTROLLER_STATE_FILENAME + '.tmp'
    try:
        with open(temporary, 'w', encoding='utf-8') as output:
            json.dump(state, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, CONTROLLER_STATE_FILENAME)
        save_quality_state()
        last_controller_state_save_time = now
    except OSError:
        logger.exception('[STATE] Failed to save controller state')

def load_controller_state():
    """Restore controller state when it is valid and no more than 24 hours old."""
    global manual_exposure_us, manual_gain, filtered_brightness, night_colour_gains
    global last_timelapse_completed_for
    try:
        with open(CONTROLLER_STATE_FILENAME, 'r', encoding='utf-8') as source:
            state = json.load(source)
        saved = datetime.fromisoformat(state['saved'])
        if saved.tzinfo is None:
            saved = saved.replace(tzinfo=HARPENDEN_TIMEZONE)
        age = local_now() - saved.astimezone(HARPENDEN_TIMEZONE)
        if age < timedelta(0) or age > timedelta(hours=CONTROLLER_STATE_MAX_AGE_HOURS):
            return False
        manual_exposure_us = state.get('manual_exposure_us')
        manual_gain = state.get('manual_gain')
        filtered_brightness = state.get('filtered_brightness')
        gains = state.get('night_colour_gains')
        night_colour_gains = (float(gains[0]), float(gains[1])) if gains and len(gains) == 2 else None
        completed_text = state.get('last_timelapse_completed_for')
        if completed_text:
            try:
                last_timelapse_completed_for = datetime.fromisoformat(completed_text).date()
            except (TypeError, ValueError):
                last_timelapse_completed_for = None
        awb_gain_history.clear()
        for item in state.get('awb_gain_history', []):
            try:
                if len(item) == 2:
                    awb_gain_history.append((float(item[0]), float(item[1])))
            except (TypeError, ValueError):
                continue
        return True
    except FileNotFoundError:
        return False
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        logger.exception('[STATE] Controller state could not be restored')
        return False
