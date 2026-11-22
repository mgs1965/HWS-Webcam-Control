"""V45-TL8-M2 physical module: timelapse.py. Loaded into the shared runtime namespace.
Do not import directly; use weather_camera.py.
"""


def unique_temporary_filename(output_filename, suffix='tmp.mp4'):
    """Return a per-process/per-thread work filename beside the final output."""
    return f'{output_filename}.{os.getpid()}.{threading.get_ident()}.{suffix}'

def probe_video(filename):
    """Read video stream metadata without decoding or counting every frame."""
    result = subprocess.run(
        [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries',
            'stream=codec_name,profile,level,width,height,pix_fmt,avg_frame_rate,duration,nb_frames,time_base:format=duration,size',
            '-of', 'json', filename,
        ],
        capture_output=True, text=True,
        timeout=TIMELAPSE_FFPROBE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1000:] or f'ffprobe returned {result.returncode}')
    data = json.loads(result.stdout)
    streams = data.get('streams') or []
    if not streams:
        raise ValueError('No video stream found')
    stream = streams[0]
    duration = float(stream.get('duration') or data.get('format', {}).get('duration') or 0.0)
    rate_text = stream.get('avg_frame_rate') or '0/1'
    numerator, separator, denominator = rate_text.partition('/')
    if separator:
        denominator_value = float(denominator or 1.0)
        fps = float(numerator or 0.0) / denominator_value if denominator_value else 0.0
    else:
        fps = float(rate_text or 0.0)
    metadata_frames = int(stream.get('nb_frames') or 0)
    estimated_frames = metadata_frames if metadata_frames > 0 else int(round(duration * fps))
    return {
        'codec_name': stream.get('codec_name'),
        'profile': stream.get('profile'),
        'level': stream.get('level'),
        'width': int(stream.get('width') or 0),
        'height': int(stream.get('height') or 0),
        'pix_fmt': stream.get('pix_fmt'),
        'fps': fps,
        'duration': duration,
        'frames': estimated_frames,
        'size': int(data.get('format', {}).get('size') or os.path.getsize(filename)),
        'time_base': stream.get('time_base'),
    }

def validate_timelapse(filename, expected_frames=None, minimum_file_size=TIMELAPSE_MIN_FILE_SIZE_BYTES):
    """Validate video metadata and duration without an expensive frame scan."""
    try:
        file_size = os.path.getsize(filename)
        if file_size < minimum_file_size:
            logger.warning('[TIMELAPSE] VALIDATION FAILED | File=%s | Reason=SMALL | Size=%d | Minimum=%d', filename, file_size, minimum_file_size)
            return False
        probe = probe_video(filename)
        minimum_frames = int(expected_frames * TIMELAPSE_MIN_FRAME_COMPLETENESS) if expected_frames else 1
        codec_ok = probe['codec_name'] == 'h264'
        dimensions_ok = probe['width'] == WEB_WIDTH and probe['height'] == WEB_HEIGHT
        format_ok = probe['pix_fmt'] == 'yuv420p'
        fps_ok = abs(probe['fps'] - TIMELAPSE_FPS) <= TIMELAPSE_FPS_TOLERANCE
        duration_ok = probe['duration'] > 0.0
        completeness_ok = probe['frames'] >= minimum_frames
        valid = codec_ok and dimensions_ok and format_ok and fps_ok and duration_ok and completeness_ok
        (logger.info if valid else logger.warning)(
            '[TIMELAPSE] VALIDATION %s | File=%s | Codec=%s | Profile=%s | Resolution=%dx%d | Pixel=%s | FPS=%.3f | Duration=%.2fs | Frames=%d | Expected=%s | Size=%.1fMB',
            'PASSED' if valid else 'FAILED', filename, probe['codec_name'], probe['profile'], probe['width'], probe['height'], probe['pix_fmt'], probe['fps'], probe['duration'], probe['frames'], expected_frames if expected_frames is not None else '--', file_size / 1024**2,
        )
        return valid
    except subprocess.TimeoutExpired:
        logger.exception('[TIMELAPSE] FFprobe timeout after %ds | File=%s', TIMELAPSE_FFPROBE_TIMEOUT_SECONDS, filename)
        return False
    except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError, IndexError):
        logger.exception('[TIMELAPSE] Validation error | File=%s', filename)
        return False

def frame_list_fingerprint(frames):
    """Create a cheap deterministic identity from ordered frame filenames."""
    import hashlib
    names = '\n'.join(os.path.basename(frame) for frame in frames)
    return hashlib.sha256(names.encode('utf-8')).hexdigest()

def get_day_frames(day):
    return sorted(glob.glob(os.path.join(FRAMES_PATH, f"frame_{day.strftime('%Y%m%d')}_*.jpg")))

def get_hour_frames(hour_start, include_current=False):
    pattern = os.path.join(FRAMES_PATH, f"frame_{hour_start:%Y%m%d_%H}*.jpg")
    frames = sorted(glob.glob(pattern))
    if include_current:
        cutoff = local_now().strftime('%Y%m%d_%H%M%S')
        frames = [frame for frame in frames if os.path.basename(frame)[6:21] <= cutoff]
    return frames

def get_hourly_segment_directory(day):
    directory = os.path.join(HOURLY_SEGMENTS_PATH, day.strftime('%Y%m%d'))
    os.makedirs(directory, exist_ok=True)
    return directory

def get_segment_manifest_filename(day):
    return os.path.join(get_hourly_segment_directory(day), TIMELAPSE_SEGMENT_MANIFEST_FILENAME)

def new_segment_manifest(day):
    return {
        'schema_version': TIMELAPSE_SEGMENT_MANIFEST_SCHEMA,
        'date': day.isoformat(),
        'video': {'codec': 'h264', 'width': WEB_WIDTH, 'height': WEB_HEIGHT, 'fps': TIMELAPSE_FPS, 'pixel_format': 'yuv420p', 'crf': TIMELAPSE_CRF, 'preset': TIMELAPSE_PRESET, 'profile': TIMELAPSE_VIDEO_PROFILE, 'level': TIMELAPSE_VIDEO_LEVEL},
        'segments': {},
    }

def load_segment_manifest(day):
    filename = get_segment_manifest_filename(day)
    with segment_manifest_lock:
        try:
            with open(filename, 'r', encoding='utf-8') as source:
                manifest = json.load(source)
            if manifest.get('schema_version') != TIMELAPSE_SEGMENT_MANIFEST_SCHEMA or manifest.get('date') != day.isoformat():
                raise ValueError('Manifest schema/date mismatch')
            if not isinstance(manifest.get('segments'), dict):
                raise ValueError('Manifest segments missing')
            return manifest
        except FileNotFoundError:
            return new_segment_manifest(day)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            logger.exception('[SEGMENT MANIFEST] Invalid manifest; rebuilding | Date=%s', day)
            try:
                if os.path.exists(filename):
                    os.replace(filename, filename + f'.invalid-{local_now():%Y%m%dT%H%M%S}')
            except OSError:
                logger.exception('[SEGMENT MANIFEST] Could not quarantine %s', filename)
            return new_segment_manifest(day)

def save_segment_manifest(day, manifest):
    filename = get_segment_manifest_filename(day)
    temporary = unique_temporary_filename(filename, 'tmp')
    manifest['updated'] = local_now().isoformat()
    with segment_manifest_lock:
        try:
            with open(temporary, 'w', encoding='utf-8') as output:
                json.dump(manifest, output, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, filename)
            logger.info('[SEGMENT MANIFEST] UPDATED | Date=%s | Segments=%d', day, len(manifest.get('segments', {})))
            return True
        except OSError:
            logger.exception('[SEGMENT MANIFEST] Save failed | Date=%s', day)
            return False
        finally:
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                pass

def manifest_entry_matches(entry, filename, frames):
    if not entry or entry.get('validation') != 'PASSED' or not os.path.exists(filename):
        return False
    try:
        return (
            int(entry.get('source_frames') or 0) == len(frames)
            and entry.get('first_frame') == os.path.basename(frames[0])
            and entry.get('last_frame') == os.path.basename(frames[-1])
            and entry.get('frame_fingerprint') == frame_list_fingerprint(frames)
            and int(entry.get('size_bytes') or 0) == os.path.getsize(filename)
        )
    except (OSError, ValueError, TypeError, IndexError):
        return False

def record_segment_manifest(day, hour_start, filename, frames, manifest):
    probe = probe_video(filename)
    manifest['segments'][f'{hour_start.hour:02d}'] = {
        'filename': os.path.basename(filename),
        'source_frames': len(frames),
        'duration_seconds': round(probe['duration'], 3),
        'size_bytes': os.path.getsize(filename),
        'first_frame': os.path.basename(frames[0]),
        'last_frame': os.path.basename(frames[-1]),
        'frame_fingerprint': frame_list_fingerprint(frames),
        'created': local_now().isoformat(),
        'validation': 'PASSED',
    }
    save_segment_manifest(day, manifest)

def remove_obsolete_partial(segment_directory, hour_start):
    partial_filename = os.path.join(segment_directory, f"partial_{hour_start:%H}.mp4")
    try:
        if os.path.exists(partial_filename):
            size = os.path.getsize(partial_filename)
            os.remove(partial_filename)
            logger.info('[HOURLY SEGMENT] Removed obsolete partial %s | Size=%.1fMB', os.path.basename(partial_filename), size / 1024**2)
            return True
    except OSError:
        logger.exception('[HOURLY SEGMENT] Could not remove obsolete partial %s', partial_filename)
    return False

def _create_timelapse_from_frames_unlocked(frames, output_filename, label, minimum_file_size=TIMELAPSE_MIN_FILE_SIZE_BYTES):
    """Encode ordered JPEGs into one profile-consistent H.264 segment."""
    if len(frames) < 2:
        return None
    concat_filename = unique_temporary_filename(output_filename, 'concat.txt')
    temporary_output = unique_temporary_filename(output_filename, 'tmp.mp4')
    with open(concat_filename, 'w', encoding='utf-8') as concat:
        for frame in frames:
            concat.write("file '%s'\n" % frame.replace("'", "'\\''"))
    command = [
        'ffmpeg', '-y', '-loglevel', 'error', '-progress', 'pipe:1', '-nostats',
        '-r', str(TIMELAPSE_FPS), '-f', 'concat', '-safe', '0', '-i', concat_filename,
        '-vf', f'scale={WEB_WIDTH}:{WEB_HEIGHT}', '-an', '-c:v', 'libx264',
        '-preset', TIMELAPSE_PRESET, '-crf', str(TIMELAPSE_CRF), '-pix_fmt', 'yuv420p',
        '-profile:v', TIMELAPSE_VIDEO_PROFILE, '-level:v', TIMELAPSE_VIDEO_LEVEL,
        '-r', str(TIMELAPSE_FPS), '-g', str(TIMELAPSE_GOP_FRAMES),
        '-keyint_min', str(TIMELAPSE_GOP_FRAMES), '-sc_threshold', '0',
        '-video_track_timescale', str(TIMELAPSE_TRACK_TIMESCALE),
        '-movflags', '+faststart', temporary_output,
    ]
    process = None
    started = time.monotonic()
    last_log = started - FFMPEG_PROGRESS_LOG_INTERVAL_SECONDS
    progress = {}
    try:
        logger.info('[FFMPEG] START | Label=%s | Frames=%d | Output=%s', label, len(frames), os.path.basename(output_filename))
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        while True:
            if time.monotonic() - started > TIMELAPSE_FFMPEG_TIMEOUT_SECONDS:
                process.kill(); process.wait(timeout=30)
                raise subprocess.TimeoutExpired(command, TIMELAPSE_FFMPEG_TIMEOUT_SECONDS)
            line = process.stdout.readline() if process.stdout else ''
            if line:
                key, separator, value = line.strip().partition('=')
                if separator:
                    progress[key] = value
                now = time.monotonic()
                if key == 'progress' and (value == 'end' or now - last_log >= FFMPEG_PROGRESS_LOG_INTERVAL_SECONDS):
                    frame = int(progress.get('frame', '0') or 0)
                    logger.info('[FFMPEG] PROGRESS | Label=%s | Frame=%d/%d | %.1f%% | FPS=%s | Speed=%s | VideoTime=%s | Size=%.1fMB | Elapsed=%.1fs', label, frame, len(frames), min(100.0, frame * 100.0 / max(len(frames), 1)), progress.get('fps', '0'), progress.get('speed', '0x'), progress.get('out_time', '00:00:00.000000'), int(progress.get('total_size', '0') or 0) / 1024**2, now - started)
                    last_log = now
            elif process.poll() is not None:
                break
            else:
                time.sleep(0.1)
        return_code = process.wait()
        stderr_text = process.stderr.read().strip() if process.stderr else ''
        if return_code != 0:
            logger.error('[FFMPEG] FAILED | Label=%s | ReturnCode=%d | Error=%s', label, return_code, stderr_text[-1000:] or 'unknown')
            return None
        if not validate_timelapse(temporary_output, len(frames), minimum_file_size):
            logger.error('[FFMPEG] VALIDATION FAILED | Label=%s | Frames=%d', label, len(frames))
            return None
        os.replace(temporary_output, output_filename)
        logger.info('[FFMPEG] COMPLETE | Label=%s | Frames=%d | Size=%.1fMB | Elapsed=%.1fs', label, len(frames), os.path.getsize(output_filename) / 1024**2, time.monotonic() - started)
        return output_filename
    except (OSError, subprocess.TimeoutExpired):
        logger.exception('[TIMELAPSE] Encode failed for %s', label)
        return None
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            try: process.wait(timeout=30)
            except subprocess.TimeoutExpired: pass
        for temporary in (concat_filename, temporary_output):
            try:
                if os.path.exists(temporary): os.remove(temporary)
            except OSError: pass

def create_timelapse_from_frames(frames, output_filename, label, minimum_file_size=TIMELAPSE_MIN_FILE_SIZE_BYTES):
    logger.info('[FFMPEG LOCK] WAIT | Label=%s', label)
    with ffmpeg_lock:
        logger.info('[FFMPEG LOCK] ACQUIRED | Label=%s', label)
        return _create_timelapse_from_frames_unlocked(frames, output_filename, label, minimum_file_size)

def build_hourly_segment(hour_start, segment_directory, manifest=None):
    """Reuse or repair one completed-hour segment from its JPEG source frames."""
    frames = get_hour_frames(hour_start)
    if len(frames) < 2:
        logger.info('[HOURLY SEGMENT] No recoverable source | Hour=%s | Frames=%d', hour_start.isoformat(), len(frames))
        return None, 0
    manifest = manifest or load_segment_manifest(hour_start.date())
    key = f'{hour_start.hour:02d}'
    filename = os.path.join(segment_directory, f'segment_{key}.mp4')
    entry = manifest.get('segments', {}).get(key)
    if manifest_entry_matches(entry, filename, frames) and validate_timelapse(filename, len(frames)):
        remove_obsolete_partial(segment_directory, hour_start)
        logger.info('[SEGMENT] REUSE | Hour=%s | Frames=%d | Size=%.1fMB', hour_start.isoformat(), len(frames), os.path.getsize(filename) / 1024**2)
        return filename, len(frames)
    if os.path.exists(filename):
        logger.warning('[SEGMENT] STALE OR INVALID | Hour=%s | Repairing', hour_start.isoformat())
    logger.info('[SEGMENT] BUILD | Hour=%s | Frames=%d', hour_start.isoformat(), len(frames))
    video = create_timelapse_from_frames(frames, filename, f'segment-{hour_start:%Y%m%d-%H}')
    if not video:
        return None, 0
    try:
        record_segment_manifest(hour_start.date(), hour_start, video, frames, manifest)
    except (OSError, RuntimeError, ValueError, TypeError, subprocess.TimeoutExpired, json.JSONDecodeError):
        logger.exception('[SEGMENT MANIFEST] Could not record hour %s', hour_start.isoformat())
    remove_obsolete_partial(segment_directory, hour_start)
    logger.info('[SEGMENT] COMPLETE | Hour=%s | Frames=%d', hour_start.isoformat(), len(frames))
    return video, len(frames)

def build_partial_hour_segment(slot_time, segment_directory):
    frames = get_hour_frames(slot_time, include_current=True)
    if len(frames) < 2:
        return None, 0
    filename = os.path.join(segment_directory, f"partial_{slot_time:%H}.mp4")
    video = create_timelapse_from_frames(frames, filename, f"partial-{slot_time:%Y%m%d-%H}", PARTIAL_TIMELAPSE_MIN_FILE_SIZE_BYTES)
    return video, len(frames) if video else 0

def _concatenate_video_segments_unlocked(segments, output_filename, expected_frames, label, minimum_file_size=TIMELAPSE_MIN_FILE_SIZE_BYTES):
    """Atomically join compatible H.264 segments using stream copy."""
    if not segments:
        return None
    concat_filename = unique_temporary_filename(output_filename, 'segments.txt')
    temporary_output = unique_temporary_filename(output_filename, 'tmp.mp4')
    with open(concat_filename, 'w', encoding='utf-8') as output:
        for segment in segments:
            output.write("file '%s'\n" % segment.replace("'", "'\\''"))
    command = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', concat_filename, '-map', '0:v:0', '-c:v', 'copy', '-movflags', '+faststart', temporary_output]
    started = time.monotonic()
    try:
        logger.info('[TIMELAPSE CONCAT] START | Label=%s | Segments=%d | Frames=%d', label, len(segments), expected_frames)
        result = subprocess.run(command, capture_output=True, text=True, timeout=TIMELAPSE_CONCAT_TIMEOUT_SECONDS)
        if result.returncode != 0:
            logger.error('[TIMELAPSE CONCAT] FAILED | Label=%s | Error=%s', label, result.stderr[-2000:] or 'unknown')
            return None
        if not validate_timelapse(temporary_output, expected_frames, minimum_file_size):
            logger.error('[TIMELAPSE CONCAT] VALIDATION FAILED | Label=%s | ExpectedFrames=%d', label, expected_frames)
            return None
        os.replace(temporary_output, output_filename)
        logger.info('[TIMELAPSE CONCAT] COMPLETE | Label=%s | Segments=%d | Frames=%d | Size=%.1fMB | Elapsed=%.1fs', label, len(segments), expected_frames, os.path.getsize(output_filename) / 1024**2, time.monotonic() - started)
        return output_filename
    except (OSError, subprocess.TimeoutExpired):
        logger.exception('[TIMELAPSE CONCAT] Failed for %s', label)
        return None
    finally:
        for temporary in (concat_filename, temporary_output):
            try:
                if os.path.exists(temporary): os.remove(temporary)
            except OSError: pass

def concatenate_video_segments(segments, output_filename, expected_frames, label, minimum_file_size=TIMELAPSE_MIN_FILE_SIZE_BYTES):
    logger.info('[FFMPEG LOCK] WAIT | Label=%s', label)
    with ffmpeg_lock:
        logger.info('[FFMPEG LOCK] ACQUIRED | Label=%s', label)
        return _concatenate_video_segments_unlocked(segments, output_filename, expected_frames, label, minimum_file_size)

def collect_today_completed_segments(slot_time, segment_directory, manifest):
    """Collect today's completed segments without rebuilding the whole day.

    Only the immediately preceding hour is eligible for routine hourly repair.
    Earlier hours are reused from the manifest. Missing, stale or invalid older
    hours are deferred to the next daily finalisation integrity sweep.
    """
    midnight = slot_time.replace(hour=0, minute=0, second=0, microsecond=0)
    previous_hour = slot_time - timedelta(hours=1)

    # The previous completed hour is the only hour built/repaired by this job.
    if previous_hour >= midnight:
        build_hourly_segment(previous_hour, segment_directory, manifest)

    segments = []
    expected_frames = 0
    hour_start = midnight
    while hour_start < slot_time:
        key = f'{hour_start.hour:02d}'
        filename = os.path.join(segment_directory, f'segment_{key}.mp4')
        entry = manifest.get('segments', {}).get(key)
        frames = get_hour_frames(hour_start)

        if manifest_entry_matches(entry, filename, frames):
            segments.append(filename)
            expected_frames += int(entry.get('source_frames') or len(frames))
            logger.info(
                '[SEGMENT] REUSE MANIFEST | Hour=%s | Frames=%d | Size=%.1fMB',
                hour_start.isoformat(),
                int(entry.get('source_frames') or len(frames)),
                os.path.getsize(filename) / 1024**2,
            )
        elif hour_start == previous_hour:
            # build_hourly_segment already attempted this hour. Do not loop.
            logger.warning(
                '[SEGMENT] PREVIOUS HOUR UNAVAILABLE | Hour=%s | Deferred to retry',
                hour_start.isoformat(),
            )
        else:
            logger.warning(
                '[SEGMENT] EARLIER HOUR DEFERRED | Hour=%s | '
                'Reason=missing-or-stale | Daily finalisation will repair',
                hour_start.isoformat(),
            )
        hour_start += timedelta(hours=1)

    return segments, expected_frames

def process_hourly_today_timelapse(slot_time):
    """Publish today-so-far while building only the previous completed hour."""
    global last_hourly_today_timelapse_completed_slot
    global hourly_today_timelapse_next_retry_time

    day = slot_time.date()
    segment_directory = get_hourly_segment_directory(day)
    output_filename = os.path.join(
        TIMELAPSE_PATH,
        HOURLY_TODAY_TIMELAPSE_LOCAL_FILENAME,
    )
    if not hourly_timelapse_lock.acquire(blocking=False):
        logger.info('[TODAY TIMELAPSE] BUSY | Slot=%s', slot_time.isoformat())
        return False

    success = False
    try:
        manifest = load_segment_manifest(day)
        logger.info(
            '[TODAY TIMELAPSE] START | Slot=%s | '
            'Policy=previous-hour-only',
            slot_time.isoformat(),
        )

        segments, expected_frames = collect_today_completed_segments(
            slot_time,
            segment_directory,
            manifest,
        )

        partial, partial_frames = build_partial_hour_segment(
            slot_time,
            segment_directory,
        )
        if partial:
            segments.append(partial)
            expected_frames += partial_frames

        logger.info(
            '[TODAY TIMELAPSE] ASSEMBLY | Slot=%s | Segments=%d | '
            'PartialFrames=%d | TotalFrames=%d',
            slot_time.isoformat(),
            len(segments),
            partial_frames,
            expected_frames,
        )

        if expected_frames < HOURLY_TODAY_TIMELAPSE_MIN_FRAMES:
            logger.info(
                '[TODAY TIMELAPSE] Insufficient frames | Slot=%s | Frames=%d',
                slot_time.isoformat(),
                expected_frames,
            )
            return False

        video = concatenate_video_segments(
            segments,
            output_filename,
            expected_frames,
            f"today-{slot_time:%Y%m%d-%H00}",
            PARTIAL_TIMELAPSE_MIN_FILE_SIZE_BYTES,
        )
        if not video:
            return False

        if UPLOAD_TIMELAPSE:
            upload_ok = upload_to_ftp(
                video,
                TODAY_TIMELAPSE_REMOTE_FILENAME,
            )
            logger.info(
                '[TODAY TIMELAPSE] FTP | Slot=%s | Success=%s',
                slot_time.isoformat(),
                upload_ok,
            )
            if not upload_ok:
                return False

        success = True
        last_hourly_today_timelapse_completed_slot = slot_time
        hourly_today_timelapse_next_retry_time = None
        hourly_today_timelapse_attempts.pop(slot_time, None)
        logger.info(
            '[TODAY TIMELAPSE] COMPLETE | Slot=%s | '
            'Segments=%d | Frames=%d',
            slot_time.isoformat(),
            len(segments),
            expected_frames,
        )
        audit_event(
            'today_timelapse_completed',
            slot=slot_time.isoformat(),
            method='previous_hour_segment_concat',
            segments=len(segments),
            frames=expected_frames,
            uploaded=UPLOAD_TIMELAPSE,
        )
        return True
    except Exception:
        logger.exception(
            '[TODAY TIMELAPSE] FAILED | Slot=%s',
            slot_time.isoformat(),
        )
        return False
    finally:
        if not success:
            hourly_today_timelapse_next_retry_time = (
                local_now()
                + timedelta(minutes=HOURLY_TIMELAPSE_RETRY_MINUTES)
            )
            logger.info(
                '[TODAY TIMELAPSE] RETRY | Slot=%s | At=%s',
                slot_time.isoformat(),
                hourly_today_timelapse_next_retry_time.isoformat(),
            )
        hourly_timelapse_lock.release()

def schedule_hourly_today_timelapse():
    global last_hourly_today_timelapse_slot, hourly_today_timelapse_thread
    if not HOURLY_TODAY_TIMELAPSE_ENABLED:
        return
    now = local_now()
    if now.minute < HOURLY_TODAY_TIMELAPSE_MINUTE:
        return
    slot = now.replace(minute=0, second=0, microsecond=0)
    if last_hourly_today_timelapse_completed_slot == slot or (hourly_today_timelapse_thread and hourly_today_timelapse_thread.is_alive()):
        return
    if hourly_today_timelapse_next_retry_time and now < hourly_today_timelapse_next_retry_time:
        return
    attempts = hourly_today_timelapse_attempts.get(slot, 0)
    if attempts >= HOURLY_TIMELAPSE_MAX_ATTEMPTS:
        return
    hourly_today_timelapse_attempts[slot] = attempts + 1
    last_hourly_today_timelapse_slot = slot
    hourly_today_timelapse_thread = threading.Thread(target=process_hourly_today_timelapse, args=(slot,), daemon=True, name='today-timelapse')
    hourly_today_timelapse_thread.start()

def collect_or_repair_daily_segments(day):
    """Return all recoverable yesterday segments and explicit unrecoverable gaps."""
    directory = get_hourly_segment_directory(day)
    manifest = load_segment_manifest(day)
    segments, expected_frames, gaps = [], 0, []
    midnight = datetime(day.year, day.month, day.day, tzinfo=HARPENDEN_TIMEZONE)
    for hour in range(24):
        hour_start = midnight + timedelta(hours=hour)
        frames = get_hour_frames(hour_start)
        key = f'{hour:02d}'
        filename = os.path.join(directory, f'segment_{key}.mp4')
        entry = manifest.get('segments', {}).get(key)
        segment, count = None, 0
        if len(frames) >= 2:
            segment, count = build_hourly_segment(hour_start, directory, manifest)
        elif entry and os.path.exists(filename):
            recorded = int(entry.get('source_frames') or 0)
            if recorded >= 2 and validate_timelapse(filename, recorded):
                segment, count = filename, recorded
                logger.info('[SEGMENT] REUSE WITHOUT FRAMES | Hour=%s | Frames=%d', hour_start.isoformat(), recorded)
        if segment:
            segments.append(segment); expected_frames += count
        elif frames or entry or os.path.exists(filename):
            gaps.append({'hour': hour_start.isoformat(), 'frames': len(frames), 'segment_exists': os.path.exists(filename)})
            logger.warning('[DAILY TIMELAPSE] SOURCE GAP | Hour=%s | Segment=%s | Frames=%d', hour_start.isoformat(), 'PRESENT' if os.path.exists(filename) else 'MISSING', len(frames))
            audit_event('daily_timelapse_source_gap', severity='WARNING', day=day.isoformat(), hour=hour, frames=len(frames), segment_exists=os.path.exists(filename))
            anomaly_window['timelapse_gaps'] += 1
    return segments, expected_frames, gaps

def create_timelapse(day):
    """Compatibility entry point: finalise a day using TL3 segment concat."""
    frames = get_day_frames(day)
    return create_timelapse_from_frames(frames, os.path.join(TIMELAPSE_PATH, f'timelapse_{day:%Y%m%d}.mp4'), f'fallback-{day:%Y%m%d}')

def select_highlight_frames(frames, center, minutes, limit=600):
    """Frames within +/- `minutes` of `center` (naive local time), thinned evenly to at most `limit`."""
    start, end = center - timedelta(minutes=minutes), center + timedelta(minutes=minutes)
    picked = []
    for frame in frames:
        try:
            taken = datetime.strptime(os.path.basename(frame)[6:21], '%Y%m%d_%H%M%S')
        except ValueError:
            continue
        if start <= taken <= end:
            picked.append(frame)
    if len(picked) > limit:
        step = len(picked) / limit
        picked = [picked[int(i * step)] for i in range(limit)]
    return picked

def build_sun_highlights(day):
    """Short clips around sunrise and sunset for the website home page; failures never affect the daily timelapse."""
    try:
        minutes = int(os.environ.get('HWS_HIGHLIGHT_MINUTES', '60'))
    except ValueError:
        minutes = 60
    frames = get_day_frames(day)
    for name, is_sunrise in (('sunrise', True), ('sunset', False)):
        try:
            moment = calculate_sun_time(day, HARPENDEN_LATITUDE, HARPENDEN_LONGITUDE, is_sunrise)
            if moment is None:
                continue
            chosen = select_highlight_frames(frames, moment.replace(tzinfo=None), minutes)
            if len(chosen) < 10:
                logger.info('[SUN HIGHLIGHT] SKIP | %s | Date=%s | Frames=%d', name, day, len(chosen))
                continue
            output = os.path.join(TIMELAPSE_PATH, f'{name}_{day:%Y%m%d}.mp4')
            if not create_timelapse_from_frames(chosen, output, f'{name}_highlight'):
                continue
            logger.info('[SUN HIGHLIGHT] COMPLETE | %s | Date=%s | Frames=%d', name, day, len(chosen))
            if UPLOAD_TIMELAPSE:
                if upload_to_ftp(output, os.path.basename(output)):
                    upload_to_ftp(output, f'latest_{name}.mp4')
        except Exception:
            logger.exception('[SUN HIGHLIGHT] FAILED | %s | Date=%s', name, day)

def process_timelapse(day):
    """Repair missing hours, concatenate available segments, and publish yesterday."""
    global last_timelapse_completed_for, next_timelapse_retry_time
    global last_timelapse_build_method, last_timelapse_segment_count
    global last_timelapse_expected_frames, last_timelapse_source_gaps
    if not daily_timelapse_lock.acquire(blocking=False):
        return False
    started = time.monotonic(); success = False
    attempts = timelapse_attempts.get(day, 0) + 1
    timelapse_attempts[day] = attempts
    output_filename = os.path.join(TIMELAPSE_PATH, f'timelapse_{day:%Y%m%d}.mp4')
    try:
        segments, expected_frames, gaps = collect_or_repair_daily_segments(day)
        last_timelapse_segment_count = len(segments)
        last_timelapse_expected_frames = expected_frames
        last_timelapse_source_gaps = gaps
        logger.info('[DAILY TIMELAPSE] SEGMENT FINALISE | Date=%s | Segments=%d | Frames=%d | Gaps=%d', day, len(segments), expected_frames, len(gaps))
        video = None
        if segments and expected_frames >= 2:
            video = concatenate_video_segments(segments, output_filename, expected_frames, f'daily-{day:%Y%m%d}')
            if video:
                last_timelapse_build_method = 'segment_concat'
        if video is None and DAILY_TIMELAPSE_FALLBACK_TO_FRAMES:
            source_frames = get_day_frames(day)
            if len(source_frames) >= 2:
                logger.warning('[DAILY TIMELAPSE] FRAME FALLBACK | Date=%s | Frames=%d | Reason=CONCAT_UNAVAILABLE', day, len(source_frames))
                audit_event('daily_timelapse_frame_fallback', severity='WARNING', day=day.isoformat(), reason='concat_unavailable', available_segments=len(segments), source_frames=len(source_frames))
                video = create_timelapse_from_frames(source_frames, output_filename, f'fallback-{day:%Y%m%d}')
                if video:
                    last_timelapse_build_method = 'frame_fallback'
                    last_timelapse_expected_frames = len(source_frames)
        if video is None:
            logger.error('[DAILY TIMELAPSE] CREATION FAILED | Date=%s | Segments=%d | Gaps=%d', day, len(segments), len(gaps))
            return False
        if UPLOAD_TIMELAPSE:
            dated_ok = upload_to_ftp(video, f'timelapse_{day:%Y%m%d}.mp4')
            latest_ok = upload_to_ftp(video, LATEST_TIMELAPSE_REMOTE_FILENAME) if dated_ok else False
            if not (dated_ok and latest_ok):
                return False
        success = True
        last_timelapse_completed_for = day
        next_timelapse_retry_time = None
        update_daily_summary_timelapse_status(day)
        save_controller_state(force=True)
        logger.info('[DAILY TIMELAPSE] COMPLETE | Date=%s | Method=%s | Segments=%d | Frames=%d | Gaps=%d | Elapsed=%.1fs', day, last_timelapse_build_method, len(segments), last_timelapse_expected_frames, len(gaps), time.monotonic() - started)
        audit_event('daily_timelapse_completed', day=day.isoformat(), method=last_timelapse_build_method, segments=len(segments), expected_frames=last_timelapse_expected_frames, source_gaps=gaps, uploaded=UPLOAD_TIMELAPSE)
        build_sun_highlights(day)
        return True
    except Exception:
        logger.exception('[DAILY TIMELAPSE] FAILED | Date=%s', day)
        return False
    finally:
        if not success:
            next_timelapse_retry_time = local_now() + timedelta(minutes=TIMELAPSE_RETRY_MINUTES)
        daily_timelapse_lock.release()

def schedule_timelapse():
    global last_timelapse_scheduled_for, timelapse_thread
    now = local_now()
    if now < now.replace(hour=TIMELAPSE_START_HOUR, minute=TIMELAPSE_START_MINUTE, second=0, microsecond=0):
        return
    yesterday = now.date() - timedelta(days=1)
    if last_timelapse_completed_for == yesterday or (timelapse_thread and timelapse_thread.is_alive()):
        return
    attempts = timelapse_attempts.get(yesterday, 0)
    if attempts >= TIMELAPSE_MAX_ATTEMPTS or (next_timelapse_retry_time and now < next_timelapse_retry_time):
        return
    last_timelapse_scheduled_for = yesterday
    timelapse_thread = threading.Thread(target=process_timelapse, args=(yesterday,), daemon=True, name='daily-timelapse')
    timelapse_thread.start()

PERIODIC_TIMELAPSE_ENABLED = True
PERIODIC_MIN_DAILY_FILES = {'weekly': 2, 'monthly': 7}
PERIODIC_MAX_ATTEMPTS = 3
PERIODIC_RETRY_MINUTES = 30
PERIODIC_CHECK_SECONDS = 600
PERIODIC_REENCODE_TIMEOUT_SECONDS = 4 * 3600
periodic_timelapse_status = {}
PERIODIC_LATEST_REMOTE = {'weekly': 'latest_weekly_timelapse.mp4', 'monthly': 'latest_monthly_timelapse.mp4'}
periodic_timelapse_lock = threading.Lock()
periodic_timelapse_thread = None
periodic_timelapse_attempts = {}
periodic_timelapse_next_retry = {}
periodic_timelapse_last_check = 0.0

def periodic_period(kind, today):
    """Return (first_day, last_day, filename) for the most recent complete week (Mon-Sun) or month."""
    if kind == 'weekly':
        last = today - timedelta(days=today.weekday() + 1)
        first = last - timedelta(days=6)
        return first, last, os.path.join(TIMELAPSE_PATH, f'weekly_timelapse_{first:%Y%m%d}.mp4')
    last = today.replace(day=1) - timedelta(days=1)
    first = last.replace(day=1)
    return first, last, os.path.join(TIMELAPSE_PATH, f'monthly_timelapse_{first:%Y%m}.mp4')

def periodic_daily_files(first, last):
    files = []
    day = first
    while day <= last:
        filename = os.path.join(TIMELAPSE_PATH, f'timelapse_{day:%Y%m%d}.mp4')
        if os.path.exists(filename):
            files.append(filename)
        day += timedelta(days=1)
    return files

def normalise_daily_video_timescale(filename, kind, output):
    """Return a stream-copied copy of a daily video on the common track timescale.

    Daily videos from different releases use different track timescales (for example 1/15360 and 1/90000); joining them
    by stream copy stretches the result, so every input is rewritten to one timescale first.
    """
    prepared = unique_temporary_filename(output, 'timescale_' + os.path.basename(filename))
    command = ['ffmpeg', '-y', '-loglevel', 'error', '-i', filename, '-map', '0:v:0', '-c:v', 'copy', '-video_track_timescale', str(TIMELAPSE_TRACK_TIMESCALE), '-movflags', '+faststart', prepared]
    result = subprocess.run(command, capture_output=True, text=True, timeout=TIMELAPSE_CONCAT_TIMEOUT_SECONDS)
    if result.returncode != 0:
        logger.error('[PERIODIC TIMELAPSE] TIMESCALE FAILED | Kind=%s | File=%s | Error=%s', kind, filename, result.stderr[-1000:] or 'unknown')
        return None
    return prepared

def periodic_uploaded_marker(filename):
    return filename + '.uploaded'

def set_periodic_status(kind, state, first, message=''):
    """Record the latest weekly/monthly outcome and log only when it changes."""
    entry = {'state': state, 'period_start': first.isoformat(), 'message': message, 'updated': local_now().isoformat()}
    previous = periodic_timelapse_status.get(kind) or {}
    periodic_timelapse_status[kind] = entry
    if (previous.get('state'), previous.get('period_start'), previous.get('message')) != (state, entry['period_start'], message):
        logger.info('[PERIODIC TIMELAPSE] %s | Kind=%s | Period=%s | %s', state.upper(), kind, first.isoformat(), message or '--')

def periodic_inputs_compatible(infos):
    """True when every daily video shares codec, size and pixel format so they can be joined by stream copy."""
    signatures = {(i.get('codec_name'), i.get('width'), i.get('height'), i.get('pix_fmt')) for i in infos}
    return len(signatures) == 1 and next(iter(signatures))[0] == 'h264'

def reencode_daily_videos(files, output, frames, label):
    """Slow fallback: re-encode the daily videos into one consistent H.264 file."""
    concat_filename = unique_temporary_filename(output, 'reencode.txt')
    temporary_output = unique_temporary_filename(output, 'tmp.mp4')
    with open(concat_filename, 'w', encoding='utf-8') as listing:
        for filename in files:
            listing.write("file '%s'\n" % filename.replace("'", "'\\''"))
    command = [
        'ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', concat_filename,
        '-vf', f'scale={WEB_WIDTH}:{WEB_HEIGHT},fps={TIMELAPSE_FPS}', '-an', '-c:v', 'libx264',
        '-preset', TIMELAPSE_PRESET, '-crf', str(TIMELAPSE_CRF), '-pix_fmt', 'yuv420p',
        '-profile:v', TIMELAPSE_VIDEO_PROFILE, '-level:v', TIMELAPSE_VIDEO_LEVEL,
        '-g', str(TIMELAPSE_GOP_FRAMES), '-keyint_min', str(TIMELAPSE_GOP_FRAMES), '-sc_threshold', '0',
        '-video_track_timescale', str(TIMELAPSE_TRACK_TIMESCALE), '-movflags', '+faststart', temporary_output,
    ]
    try:
        with ffmpeg_lock:
            logger.info('[PERIODIC TIMELAPSE] REENCODE START | Label=%s | Files=%d | Frames=%d', label, len(files), frames)
            result = subprocess.run(command, capture_output=True, text=True, timeout=PERIODIC_REENCODE_TIMEOUT_SECONDS)
            if result.returncode != 0:
                logger.error('[PERIODIC TIMELAPSE] REENCODE FAILED | Label=%s | Error=%s', label, result.stderr[-1000:] or 'unknown')
                return None
            if not validate_timelapse(temporary_output, frames, 1):
                return None
            os.replace(temporary_output, output)
            return output
    except (OSError, subprocess.TimeoutExpired):
        logger.exception('[PERIODIC TIMELAPSE] REENCODE FAILED | Label=%s', label)
        return None
    finally:
        for temporary in (concat_filename, temporary_output):
            try:
                if os.path.exists(temporary): os.remove(temporary)
            except OSError: pass

def join_daily_videos(files, infos, output, frames, label, kind):
    """Join by stream copy when the inputs are compatible, otherwise (or if that fails) by re-encoding."""
    if periodic_inputs_compatible(infos):
        prepared = []
        try:
            for filename in files:
                item = normalise_daily_video_timescale(filename, kind, output)
                if not item:
                    break
                prepared.append(item)
            else:
                if concatenate_video_segments(prepared, output, frames, label, minimum_file_size=1):
                    return True
        finally:
            for temporary in prepared:
                try:
                    os.remove(temporary)
                except OSError:
                    pass
        logger.warning('[PERIODIC TIMELAPSE] STREAM COPY FAILED | Label=%s | Falling back to re-encode', label)
    else:
        logger.warning('[PERIODIC TIMELAPSE] INPUTS INCOMPATIBLE | Label=%s | Using re-encode', label)
    return bool(reencode_daily_videos(files, output, frames, label))

def build_periodic_timelapse(kind, today):
    """Join the existing daily videos of the previous full week/month; True when nothing remains to do."""
    first, last, output = periodic_period(kind, today)
    upload = UPLOAD_TIMELAPSE and (UPLOAD_WEEKLY_TIMELAPSE if kind == 'weekly' else UPLOAD_MONTHLY_TIMELAPSE)
    if os.path.exists(output) and (not upload or os.path.exists(periodic_uploaded_marker(output))):
        set_periodic_status(kind, 'complete', first, os.path.basename(output))
        return True
    if not os.path.exists(output):
        files = periodic_daily_files(first, last)
        if len(files) < PERIODIC_MIN_DAILY_FILES[kind]:
            set_periodic_status(kind, 'skipped', first, f'only {len(files)} daily videos, need {PERIODIC_MIN_DAILY_FILES[kind]}')
            return True
        infos = [probe_video(filename) for filename in files]
        frames = sum(int(info.get('frames') or 0) for info in infos)
        if frames < 2:
            set_periodic_status(kind, 'failed', first, 'daily videos contain no frames')
            return False
        set_periodic_status(kind, 'building', first, f'{len(files)} daily videos, {frames} frames')
        if not join_daily_videos(files, infos, output, frames, f'{kind}-{first:%Y%m%d}', kind):
            set_periodic_status(kind, 'failed', first, 'join failed')
            return False
        audit_event(f'{kind}_timelapse_completed', first_day=first.isoformat(), last_day=last.isoformat(), daily_files=len(files), frames=frames)
    if upload:
        if not (upload_to_ftp(output, os.path.basename(output)) and upload_to_ftp(output, PERIODIC_LATEST_REMOTE[kind])):
            set_periodic_status(kind, 'failed', first, 'upload failed')
            return False
        with open(periodic_uploaded_marker(output), 'w', encoding='utf-8') as marker:
            marker.write(local_now().isoformat())
    set_periodic_status(kind, 'complete', first, os.path.basename(output))
    return True

def process_periodic_timelapses(today):
    if not periodic_timelapse_lock.acquire(blocking=False):
        return
    try:
        for kind in ('weekly', 'monthly'):
            first = periodic_period(kind, today)[0]
            key = (kind, first, today)
            if periodic_timelapse_attempts.get(key, 0) >= PERIODIC_MAX_ATTEMPTS:
                continue
            retry_key = (kind, first)
            if retry_key in periodic_timelapse_next_retry and local_now() < periodic_timelapse_next_retry[retry_key]:
                continue
            periodic_timelapse_attempts[key] = periodic_timelapse_attempts.get(key, 0) + 1
            try:
                ok = build_periodic_timelapse(kind, today)
            except Exception:
                logger.exception('[PERIODIC TIMELAPSE] FAILED | Kind=%s', kind)
                set_periodic_status(kind, 'failed', first, 'unexpected error')
                ok = False
            if ok:
                periodic_timelapse_attempts[key] = 0
                periodic_timelapse_next_retry[retry_key] = local_now() + timedelta(days=1)
            elif periodic_timelapse_attempts[key] >= PERIODIC_MAX_ATTEMPTS:
                logger.error('[PERIODIC TIMELAPSE] GIVING UP TODAY | Kind=%s | Period=%s | Attempts=%d | Will retry tomorrow', kind, first.isoformat(), PERIODIC_MAX_ATTEMPTS)
                audit_event('periodic_timelapse_gave_up', severity='ERROR', kind=kind, period_start=first.isoformat())
            else:
                periodic_timelapse_next_retry[retry_key] = local_now() + timedelta(minutes=PERIODIC_RETRY_MINUTES)
    finally:
        periodic_timelapse_lock.release()

def schedule_periodic_timelapses():
    """Rate-limited background check for weekly and monthly summary videos."""
    global periodic_timelapse_thread, periodic_timelapse_last_check
    if not PERIODIC_TIMELAPSE_ENABLED or (periodic_timelapse_thread and periodic_timelapse_thread.is_alive()):
        return
    if time.monotonic() - periodic_timelapse_last_check < PERIODIC_CHECK_SECONDS:
        return
    periodic_timelapse_last_check = time.monotonic()
    now = local_now()
    if now < now.replace(hour=TIMELAPSE_START_HOUR, minute=TIMELAPSE_START_MINUTE + 30, second=0, microsecond=0):
        return
    if last_timelapse_completed_for != now.date() - timedelta(days=1):
        return
    periodic_timelapse_thread = threading.Thread(target=process_periodic_timelapses, args=(now.date(),), daemon=True, name='periodic-timelapse')
    periodic_timelapse_thread.start()
