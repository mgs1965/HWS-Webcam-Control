"""V45-TL8-M2 physical module: camera.py. Loaded into the shared runtime namespace.
Do not import directly; use weather_camera.py.
"""

class CameraAcquisitionError(RuntimeError):
    """Raised only when Picamera2 fails to acquire a request or frame."""
picam2 = Picamera2()
camera_configuration = picam2.create_still_configuration(main={'size': (SENSOR_WIDTH, SENSOR_HEIGHT), 'format': CAMERA_PIXEL_FORMAT}, buffer_count=3)
picam2.configure(camera_configuration)


def normalise_camera_array(image_array):
    if FORCE_SWAP_RED_BLUE:
        return image_array[:, :, ::-1].copy()
    return image_array

def convert_array_to_image(image_array):
    return Image.fromarray(image_array).convert('RGB')

def create_web_image(full_image):
    """Centre-crop the 4:3 sensor image to 16:9 and resize for web output."""
    width, height = full_image.size
    new_height = int(width / (WEB_WIDTH / WEB_HEIGHT))
    top = (height - new_height) // 2
    return full_image.crop((0, top, width, top + new_height)).resize((WEB_WIDTH, WEB_HEIGHT), Image.Resampling.LANCZOS)

def load_overlay_font():
    try:
        return ImageFont.truetype(FONT_PATH, round(BASE_FONT_SIZE * WEB_WIDTH / BASE_WEB_WIDTH))
    except OSError:
        return ImageFont.load_default()

OVERLAY_FONT = load_overlay_font()

def add_overlay(image, capture_time, metadata, measurement):
    image = image.convert('RGB')
    draw = ImageDraw.Draw(image)
    left_text = f'{STATION_NAME} | {current_camera_mode} | Sun {current_solar_elevation:.1f} deg'
    right_text = capture_time.strftime('%d %b %Y %H:%M:%S') + f" | {metadata.get('ExposureTime', 0) / 1000:.0f}ms | G{metadata.get('AnalogueGain', 0):.2f} | B{measurement['brightness']:.0f}"
    scale = WEB_WIDTH / BASE_WEB_WIDTH
    padding = round(BASE_PADDING * scale)
    overlay_margin = round(BASE_OVERLAY_MARGIN * scale)
    left_box = draw.textbbox((0, 0), left_text, font=OVERLAY_FONT)
    right_box = draw.textbbox((0, 0), right_text, font=OVERLAY_FONT)
    overlay_height = max(left_box[3] - left_box[1], right_box[3] - right_box[1]) + overlay_margin
    overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle((0, image.height - overlay_height, image.width, image.height), fill=(0, 0, 0, 145))
    image = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(image)
    y = image.height - overlay_height + overlay_margin // 2
    draw.text((padding, y), left_text, font=OVERLAY_FONT, fill='white')
    right_width = right_box[2] - right_box[0]
    draw.text((image.width - right_width - padding, y), right_text, font=OVERLAY_FONT, fill='white')
    top_left, top_right = scene_overlay_texts(measurement)
    if top_left or top_right:
        top_text = [text for text in (top_left, top_right) if text]
        top_height = max(draw.textbbox((0, 0), text, font=OVERLAY_FONT)[3] for text in top_text) + overlay_margin
        top_overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
        ImageDraw.Draw(top_overlay).rectangle((0, 0, image.width, top_height), fill=(0, 0, 0, 145))
        image = Image.alpha_composite(image.convert('RGBA'), top_overlay).convert('RGB')
        draw = ImageDraw.Draw(image)
        if top_left:
            draw.text((padding, overlay_margin // 2), top_left, font=OVERLAY_FONT, fill='white')
        if top_right:
            width = draw.textbbox((0, 0), top_right, font=OVERLAY_FONT)
            draw.text((image.width - (width[2] - width[0]) - padding, overlay_margin // 2), top_right, font=OVERLAY_FONT, fill='white')
    return image

def save_jpeg_atomic(image, filename):
    temporary = filename + '.tmp'
    image.save(temporary, format='JPEG', quality=WEB_JPEG_QUALITY, optimize=True)
    os.replace(temporary, filename)

def replace_latest_image(source_filename):
    temporary = LOCAL_LATEST_IMAGE_FILENAME + '.tmp'
    shutil.copyfile(source_filename, temporary)
    os.replace(temporary, LOCAL_LATEST_IMAGE_FILENAME)

def capture_frame():
    """Execute one complete capture, meter, control, archive and telemetry cycle."""
    global capture_count, capture_processing_total_ms, capture_processing_max_ms, last_capture_time
    started = time.monotonic()
    configure_camera_mode()
    try:
        with camera_lock:
            request = picam2.capture_request()
            try:
                image_array = request.make_array('main')
                metadata = request.get_metadata()
            finally:
                request.release()
    except Exception as error:
        raise CameraAcquisitionError(str(error)) from error
    capture_time = local_now()
    image_array = normalise_camera_array(image_array)
    measurement = measure_image(image_array)
    update_awb_learning(metadata)
    update_manual_exposure(measurement, metadata)
    update_image_quality(measurement)
    try:
        update_scene_analysis(image_array, measurement)
        record_scene_history(capture_time, measurement)
        record_keogram_slice(image_array, capture_time)
    except Exception:
        logger.exception('[SCENE] Scene analysis or keogram failed; capture continues')
    contrast_limit = {'DAY': DAY_CONTRAST_WARNING, 'TWILIGHT': TWILIGHT_CONTRAST_WARNING, 'LOW LIGHT': LOW_LIGHT_CONTRAST_WARNING}.get(current_camera_mode, NIGHT_CONTRAST_WARNING)
    if measurement['contrast'] < contrast_limit and measurement.get('night_observability') != 'GATED':
        logger.warning('[LOW CONTRAST] Mode=%s Contrast=%.1f Limit=%.1f', current_camera_mode, measurement['contrast'], contrast_limit)
    web_image = add_overlay(create_web_image(convert_array_to_image(image_array)), capture_time, metadata, measurement)
    del image_array
    timestamp = capture_time.strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(FRAMES_PATH, f'frame_{timestamp}.jpg')
    if get_free_space_gb() >= DISK_LIVE_ONLY_GB:
        save_jpeg_atomic(web_image, filename)
        replace_latest_image(filename)
    else:
        filename = LOCAL_LATEST_IMAGE_FILENAME
        save_jpeg_atomic(web_image, filename)
        audit_event('live_only_storage_mode', severity='ERROR', free_space_gb=round(get_free_space_gb(), 2))
    processing_ms = (time.monotonic() - started) * 1000.0
    capture_count += 1
    capture_processing_total_ms += processing_ms
    capture_processing_max_ms = max(capture_processing_max_ms, processing_ms)
    global telemetry_failure_count, status_failure_count
    telemetry_filename = append_monthly_telemetry(capture_time, metadata, measurement, processing_ms)
    if telemetry_filename is None:
        telemetry_failure_count += 1
        audit_event('telemetry_write_failure', severity='ERROR', capture_time=capture_time.isoformat())
    try:
        status_filename = write_status_file(capture_time, metadata, measurement)
        try:
            record_controller_analytics(capture_time, metadata, measurement)
        except Exception:
            logger.exception('[ANALYTICS] Controller analytics update failed; capture cycle will continue')
    except OSError:
        status_failure_count += 1
        logger.exception('[STATUS] Status file write failed')
        audit_event('status_write_failure', severity='ERROR', capture_time=capture_time.isoformat())
        status_filename = None
    last_capture_time = capture_time
    save_controller_state()
    if measurement['image_quality_status'] == 'SETTLING':
        baseline_text = f"SETTLING {measurement['quality_settling_capture']}/{measurement['quality_settling_required']}"
        sharpness_ratio_text = '--'
        quality_text = '-- SETTLING'
    elif measurement['image_quality_status'] == 'UNOBSERVABLE':
        baseline_text = f"{measurement['sharpness_baseline']:.2f}" if measurement.get('sharpness_baseline') is not None else '--'
        sharpness_ratio_text = f"{measurement['sharpness_ratio']:.2f}" if measurement.get('sharpness_ratio') is not None else '--'
        quality_text = '-- UNOBSERVABLE'
    elif measurement['image_quality_status'] == 'LEARNING':
        baseline_text = f"LEARNING {measurement['quality_learning_samples']}/{measurement['quality_learning_required']}"
        sharpness_ratio_text = '--'
        quality_text = '-- LEARNING'
    else:
        baseline_text = f"{measurement['sharpness_baseline']:.2f}"
        sharpness_ratio_text = f"{measurement['sharpness_ratio']:.2f}"
        quality_text = f"{measurement['image_quality_score']:.1f} {measurement['image_quality_status']}"
    cpu_temperature_c = get_cpu_temperature_c()
    cpu_temperature_text = f'{cpu_temperature_c:.1f}' if cpu_temperature_c is not None else '--'
    logger.info('[CAPTURE] %s | %s | Sun %.2f | Exp %.0fms | G %.2f | DG %.2f | B %.1f | C %.1f | H %.2f%% | S %.2f | SB %s | SR %s | ED %.2f%% | Q %s | Lens %s | Obs %s | CPU %sC | Proc %.0fms', timestamp, current_camera_mode, current_solar_elevation, metadata.get('ExposureTime', 0) / 1000.0, metadata.get('AnalogueGain', 0), metadata.get('DigitalGain', 0), measurement['brightness'], measurement['contrast'], measurement['highlights'], measurement['sharpness_score'], baseline_text, sharpness_ratio_text, measurement['edge_density'], quality_text, measurement['lens_status'], measurement.get('night_observability', 'N/A'), cpu_temperature_text, processing_ms)
    try:
        update_mode_validation(measurement, metadata.get('ExposureTime', 0), metadata.get('AnalogueGain', 0.0))
    except Exception:
        logger.exception('[MODE VALIDATION] Unexpected failure isolated from capture cycle')
    record_capture_anomalies(measurement, processing_ms, cpu_temperature_c)
    return (filename, status_filename, capture_time)

def restart_camera():
    """Restart Picamera2 after repeated failures and reapply the active mode."""
    global camera_restart_count
    now = local_now()
    while camera_restart_times and (now - camera_restart_times[0]).total_seconds() > 3600:
        camera_restart_times.popleft()
    if len(camera_restart_times) >= V50_MAX_CAMERA_RESTARTS_PER_HOUR:
        logger.critical('[CAMERA] Restart limit reached: %d/hour; manual intervention required', V50_MAX_CAMERA_RESTARTS_PER_HOUR)
        audit_event('camera_restart_limit', severity='CRITICAL', restart_count=camera_restart_count)
        return False
    camera_restart_count += 1
    camera_restart_times.append(now)
    logger.warning('[CAMERA] Restarting')
    audit_event('camera_restart', severity='WARNING', restart_count=camera_restart_count)
    try:
        with camera_lock:
            try:
                picam2.stop()
            except Exception:
                logger.exception('[CAMERA] Error while stopping camera for restart')
            if shutdown_event.wait(CAMERA_RESTART_DELAY_SECONDS):
                return False
            picam2.configure(camera_configuration)
            picam2.start()
            if shutdown_event.wait(CAMERA_RESTART_SETTLE_SECONDS):
                return False
        configure_camera_mode(force=True)
        return True
    except Exception as error:
        logger.exception('[CAMERA] Restart failed')
        audit_event('camera_restart_failed', severity='ERROR', restart_count=camera_restart_count, error=str(error))
        return False
