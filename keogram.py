"""V52.16 physical module: keogram.py. Loaded into the shared runtime namespace.
Do not import directly; use weather_camera.py.

A daily keogram (slit-scan) stacks one thin vertical slice of the camera view
per minute of the day into a single image, showing sunrise, cloud movement and
sunset at a glance. Slices are written to a preallocated per-day raw file so
memory use is constant and a service restart loses nothing.
"""

KEOGRAM_ENABLED = True
KEOGRAM_PATH = os.path.join(LOCAL_SAVE_PATH, 'keogram')
KEOGRAM_HEIGHT = 360
KEOGRAM_COLUMNS = 1440
KEOGRAM_SLICE_WIDTH = 16
KEOGRAM_MIN_COLUMNS = 30
KEOGRAM_LABEL_HEIGHT = 20
KEOGRAM_RETENTION_DAYS = 90
KEOGRAM_UPLOAD = True
KEOGRAM_LATEST_REMOTE_FILENAME = 'latest_keogram.png'
KEOGRAM_MAX_ATTEMPTS = 6
KEOGRAM_RETRY_MINUTES = 30
os.makedirs(KEOGRAM_PATH, exist_ok=True)

keogram_lock = threading.Lock()
keogram_thread = None
keogram_last_column = None
keogram_attempts = {}
keogram_next_retry = {}


def keogram_raw_filename(day):
    return os.path.join(KEOGRAM_PATH, f'keogram_{day:%Y%m%d}.raw')

def keogram_png_filename(day):
    return os.path.join(KEOGRAM_PATH, f'keogram_{day:%Y%m%d}.png')

def keogram_uploaded_marker(day):
    return os.path.join(KEOGRAM_PATH, f'keogram_{day:%Y%m%d}.uploaded')

def extract_keogram_slice(image_array):
    """Average a narrow centre band of the 16:9 web crop into one KEOGRAM_HEIGHT pixel column."""
    height, width = image_array.shape[:2]
    crop_height = min(height, int(width * WEB_HEIGHT / WEB_WIDTH))
    top = (height - crop_height) // 2
    left = max(0, width // 2 - KEOGRAM_SLICE_WIDTH // 2)
    band = image_array[top:top + crop_height, left:left + KEOGRAM_SLICE_WIDTH, :3]
    rows = np.linspace(0, crop_height - 1, KEOGRAM_HEIGHT).astype(int)
    return band[rows].astype(np.float32).mean(axis=1).round().astype(np.uint8)

def write_keogram_slice(slice_pixels, capture_time):
    """Store a slice at its minute-of-day position in the day's preallocated raw file."""
    filename = keogram_raw_filename(capture_time.date())
    column_bytes = KEOGRAM_HEIGHT * 3
    minute = min(KEOGRAM_COLUMNS - 1, capture_time.hour * 60 + capture_time.minute)
    with keogram_lock:
        if not os.path.exists(filename) or os.path.getsize(filename) != KEOGRAM_COLUMNS * column_bytes:
            with open(filename, 'wb') as output:
                output.truncate(KEOGRAM_COLUMNS * column_bytes)
        with open(filename, 'r+b') as output:
            output.seek(minute * column_bytes)
            output.write(np.ascontiguousarray(slice_pixels).tobytes())

def record_keogram_slice(image_array, capture_time):
    """Record at most one slice per minute; returns True when a slice was written."""
    global keogram_last_column
    if not KEOGRAM_ENABLED:
        return False
    column_key = (capture_time.date(), capture_time.hour, capture_time.minute)
    if column_key == keogram_last_column:
        return False
    write_keogram_slice(extract_keogram_slice(image_array), capture_time)
    keogram_last_column = column_key
    return True

def render_keogram_image(raw_filename):
    """Build the labelled keogram image from a raw file, or None if too sparse."""
    column_bytes = KEOGRAM_HEIGHT * 3
    with open(raw_filename, 'rb') as source:
        data = source.read()
    if len(data) != KEOGRAM_COLUMNS * column_bytes:
        return None
    columns = np.frombuffer(data, dtype=np.uint8).reshape(KEOGRAM_COLUMNS, KEOGRAM_HEIGHT, 3)
    if int(np.count_nonzero(columns.any(axis=(1, 2)))) < KEOGRAM_MIN_COLUMNS:
        return None
    canvas = np.zeros((KEOGRAM_HEIGHT + KEOGRAM_LABEL_HEIGHT, KEOGRAM_COLUMNS, 3), dtype=np.uint8)
    canvas[:KEOGRAM_HEIGHT] = columns.transpose(1, 0, 2)
    image = Image.fromarray(canvas)
    draw = ImageDraw.Draw(image)
    for hour in range(0, 24, 3):
        x = hour * 60
        draw.line((x, KEOGRAM_HEIGHT, x, KEOGRAM_HEIGHT + 5), fill=(255, 255, 255))
        draw.text((x + 3, KEOGRAM_HEIGHT + 6), f'{hour:02d}:00', fill=(255, 255, 255))
    return image

def finalise_keogram(day):
    """Render and publish a completed day; returns True when nothing remains to do."""
    raw = keogram_raw_filename(day)
    png = keogram_png_filename(day)
    if os.path.exists(raw):
        image = render_keogram_image(raw)
        if image is None:
            logger.warning('[KEOGRAM] Discarding sparse or invalid data | Date=%s', day)
            os.remove(raw)
            return True
        temporary = png + '.tmp'
        image.save(temporary, format='PNG', optimize=True)
        os.replace(temporary, png)
        os.remove(raw)
        logger.info('[KEOGRAM] COMPLETE | Date=%s | Size=%.1fKB', day, os.path.getsize(png) / 1024.0)
        audit_event('keogram_completed', day=day.isoformat())
    if not os.path.exists(png):
        return True
    if KEOGRAM_UPLOAD and not os.path.exists(keogram_uploaded_marker(day)):
        if not (upload_to_ftp(png, f'keogram_{day:%Y%m%d}.png') and upload_to_ftp(png, KEOGRAM_LATEST_REMOTE_FILENAME)):
            return False
        with open(keogram_uploaded_marker(day), 'w', encoding='utf-8') as marker:
            marker.write(local_now().isoformat())
    return True

def pending_keogram_days(today):
    """Past days with an unrendered raw file or a rendered image awaiting upload."""
    days = set()
    for filename in glob.glob(os.path.join(KEOGRAM_PATH, 'keogram_*.raw')) + glob.glob(os.path.join(KEOGRAM_PATH, 'keogram_*.png')):
        try:
            day = datetime.strptime(os.path.basename(filename)[8:16], '%Y%m%d').date()
        except ValueError:
            continue
        if day >= today:
            continue
        if filename.endswith('.png') and (not KEOGRAM_UPLOAD or os.path.exists(keogram_uploaded_marker(day))):
            continue
        if keogram_attempts.get(day, 0) >= KEOGRAM_MAX_ATTEMPTS or (day in keogram_next_retry and local_now() < keogram_next_retry[day]):
            continue
        days.add(day)
    return sorted(days)

def process_pending_keograms(today):
    for day in pending_keogram_days(today):
        keogram_attempts[day] = keogram_attempts.get(day, 0) + 1
        try:
            if finalise_keogram(day):
                continue
        except Exception:
            logger.exception('[KEOGRAM] FAILED | Date=%s', day)
        keogram_next_retry[day] = local_now() + timedelta(minutes=KEOGRAM_RETRY_MINUTES)

def schedule_keogram_finalise():
    """Start a background pass over completed days; safe to call every capture cycle."""
    global keogram_thread
    if not KEOGRAM_ENABLED or (keogram_thread and keogram_thread.is_alive()):
        return
    today = local_now().date()
    if not pending_keogram_days(today):
        return
    keogram_thread = threading.Thread(target=process_pending_keograms, args=(today,), daemon=True, name='keogram')
    keogram_thread.start()

def cleanup_old_keograms():
    cutoff = (local_now() - timedelta(days=KEOGRAM_RETENTION_DAYS)).timestamp()
    for pattern in ('keogram_*.png', 'keogram_*.uploaded', 'keogram_*.raw'):
        for filename in glob.glob(os.path.join(KEOGRAM_PATH, pattern)):
            try:
                if os.path.getmtime(filename) < cutoff:
                    os.remove(filename)
            except OSError:
                logger.warning('[STORAGE] Could not process %s', filename)
