#!/usr/bin/env python3
"""Harpenden Weather Station camera controller, compressed V41.

V41 is a maintenance refactor of corrected V40. It preserves camera modes,
manual exposure behaviour, image-quality monitoring, state persistence,
telemetry, FTP snapshots, daily/hourly timelapses, retention, recovery and
logging. The source is canonicalised to remove repetitive formatting and
comments without intentionally changing runtime behaviour.
"""

import hashlib
import platform
import socket
import csv
import ftplib
import glob
import gzip
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import math
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np
from libcamera import controls
from picamera2 import Picamera2
from PIL import Image, ImageDraw, ImageFont
SCRIPT_VERSION = '2026-11-19 V52.6'
LOCAL_SAVE_PATH = '/mnt/weathercam'
LOGS_PATH = os.path.join(LOCAL_SAVE_PATH, 'logs')
FRAMES_PATH = os.path.join(LOCAL_SAVE_PATH, 'frames')
TIMELAPSE_PATH = os.path.join(LOCAL_SAVE_PATH, 'timelapse')
HOURLY_SEGMENTS_PATH = os.path.join(TIMELAPSE_PATH, 'hourly_segments')
for directory in (LOCAL_SAVE_PATH, LOGS_PATH, FRAMES_PATH, TIMELAPSE_PATH, HOURLY_SEGMENTS_PATH):
    os.makedirs(directory, exist_ok=True)
WEB_FRAME_RETENTION_DAYS = 7
VIDEO_RETENTION_DAYS = 37
PERIODIC_WEEKLY_RETENTION_DAYS = 365
PERIODIC_MONTHLY_RETENTION_DAYS = 1095
HOUSEKEEPING_INTERVAL_HOURS = 24
APPLICATION_LOG_RETENTION_DAYS = 30
TELEMETRY_FILENAME_PREFIX = 'camera_telemetry'
TELEMETRY_FLUSH_EACH_ROW = True
TELEMETRY_RETENTION_MONTHS = 24
DAILY_SUMMARY_RETENTION_DAYS = 730
# V47.3 system-health observability. Health history is separate from the immutable
# 58-field capture telemetry contract.
HEALTH_HISTORY_PATH = os.path.join(LOCAL_SAVE_PATH, 'telemetry', 'health')
HEALTH_SNAPSHOT_INTERVAL_MINUTES = 60
HEALTH_HISTORY_RETENTION_DAYS = 730
HEALTH_SCHEMA_VERSION = 1
HEALTH_CPU_WARNING_C = 70.0
HEALTH_CPU_CRITICAL_C = 80.0
HEALTH_DISK_WARNING_PERCENT = 85.0
HEALTH_DISK_CRITICAL_PERCENT = 95.0
HEALTH_MEMORY_WARNING_PERCENT = 85.0
HEALTH_MEMORY_CRITICAL_PERCENT = 95.0
DISK_WARNING_GB = 10.0
DISK_AGGRESSIVE_CLEANUP_GB = 5.0
DISK_CRITICAL_GB = 2.0
DISK_LIVE_ONLY_GB = 1.0
CONTROLLER_STATE_FILENAME = os.path.join(LOGS_PATH, 'camera_controller_state.json')
CONTROLLER_STATE_MAX_AGE_HOURS = 24
CONTROLLER_STATE_SAVE_INTERVAL_MINUTES = 10
LOCAL_LATEST_IMAGE_FILENAME = os.path.join(FRAMES_PATH, 'latest.jpg')
AUDIT_LOG_FILENAME_PREFIX = 'camera_audit'
AUDIT_LOG_RETENTION_DAYS = 365
AUDIT_FSYNC_EACH_EVENT = True
SENSOR_WIDTH = 4056
SENSOR_HEIGHT = 3040
WEB_WIDTH = 2560
WEB_HEIGHT = 1440
CAMERA_PIXEL_FORMAT = 'BGR888'
CAPTURE_INTERVAL_SECONDS = 10
WEB_JPEG_QUALITY = 95
FORCE_SWAP_RED_BLUE = False
STATION_NAME = 'Harpenden Weather Station'
FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
BASE_WEB_WIDTH = 1920
BASE_FONT_SIZE = 22
BASE_PADDING = 15
BASE_OVERLAY_MARGIN = 20
FTP_SERVER = 'ftp.harpendenweatherstation.co.uk'
FTP_USERNAME = 'harpendenweatherstation.co.uk'
FTP_PASSWORD = os.getenv('HWS_FTP_PASSWORD', '')
if not FTP_PASSWORD:
    raise RuntimeError('HWS_FTP_PASSWORD is not configured. Set it in the service environment.')
FTP_UPLOAD_PATH = '/public_html'
LATEST_IMAGE_REMOTE_FILENAME = 'newcam.jpg'
LATEST_STATUS_REMOTE_FILENAME = 'camera_status.json'
LATEST_TIMELAPSE_REMOTE_FILENAME = 'latest_timelapse.mp4'
TODAY_TIMELAPSE_REMOTE_FILENAME = 'today_timelapse.mp4'
FTP_TIMEOUT_SECONDS = 30
FTP_MAX_RETRIES = 3
FTP_RETRY_DELAY_SECONDS = 5
FTP_HEALTH_DEGRADED_FAILURES = 1
FTP_HEALTH_OUTAGE_FAILURES = 3
FTP_HEALTH_RECOVERY_SUCCESSES = 2
FTP_HEALTH_LOG_SUPPRESSION_SECONDS = 60
FTP_WORKER_SHUTDOWN_TIMEOUT_SECONDS = 2 * FTP_MAX_RETRIES * (FTP_TIMEOUT_SECONDS + FTP_RETRY_DELAY_SECONDS) + 10
HARPENDEN_LATITUDE = 51.8175
HARPENDEN_LONGITUDE = -0.352
HARPENDEN_TIMEZONE = ZoneInfo('Europe/London')
UTC_TIMEZONE = ZoneInfo('UTC')
DAY_ELEVATION = 0.5
LOW_LIGHT_ELEVATION = -1.5
NIGHT_ELEVATION = -5.0
SOLAR_MODE_HYSTERESIS_DEGREES = 0.25
DAY_SHARPNESS = 1.8
TWILIGHT_SHARPNESS = 1.4
LOW_LIGHT_SHARPNESS = 0.8
NIGHT_SHARPNESS = 0.7
DAY_CAMERA_CONTROLS = {'AeEnable': True, 'AwbEnable': True, 'AwbMode': controls.AwbModeEnum.Daylight, 'ExposureValue': -0.5, 'Brightness': 0.0, 'Contrast': 1.0, 'Saturation': 1.15, 'Sharpness': DAY_SHARPNESS}
LOW_LIGHT_INITIAL_EXPOSURE_US = 80000
NIGHT_INITIAL_EXPOSURE_US = LOW_LIGHT_INITIAL_EXPOSURE_US
INITIAL_LOW_LIGHT_GAIN = 1.4
MIN_EXPOSURE_US = 1000
MAX_TWILIGHT_EXPOSURE_US = 1000000
MAX_LOW_LIGHT_EXPOSURE_US = 1500000
MAX_NIGHT_EXPOSURE_US = 4500000
MIN_ANALOGUE_GAIN = 1.0
ABSOLUTE_MAX_GAIN = 4.0
MAX_EXPOSURE_CHANGE_FRACTION = 0.15
MAX_GAIN_CHANGE_FRACTION = 0.1
TWILIGHT_TARGET_LOW = 78.0
TWILIGHT_TARGET_HIGH = 100.0
LOW_LIGHT_TARGET_LOW = 45.0
LOW_LIGHT_TARGET_HIGH = 72.0
NIGHT_TARGET_LOW = 25.0
NIGHT_TARGET_HIGH = 45.0
# NIGHT observability gate: a NIGHT frame must contain enough real scene signal
# before it may train the quality baseline or be reported as a healthy clear view.
NIGHT_OBSERVABILITY_MIN_BRIGHTNESS = 18.0
NIGHT_OBSERVABILITY_MIN_CONTRAST = 10.0
NIGHT_OBSERVABILITY_MIN_EDGE_DENSITY = 0.25
NIGHT_OBSERVABILITY_MIN_SHARPNESS_RATIO = 0.55
NIGHT_OBSERVABILITY_RECOVERY_CAPTURES = 3
NIGHT_OBSERVABILITY_FAILURE_CAPTURES = 3
QUALITY_STATE_SCHEMA_VERSION = 2
TWILIGHT_BRIGHTNESS_DEADBAND = 2.0
LOW_LIGHT_BRIGHTNESS_DEADBAND = 2.0
NIGHT_BRIGHTNESS_DEADBAND = 1.0
METERING_PERCENTILE = 60.0
LOW_LIGHT_MAX_HIGHLIGHT_PERCENT = 2.0
NIGHT_MAX_HIGHLIGHT_PERCENT = 5.0
HIGHLIGHT_THRESHOLD = 250
SHADOW_THRESHOLD = 5
SKY_WEIGHT = 0.6
HORIZON_WEIGHT = 0.3
FOREGROUND_WEIGHT = 0.1
METERING_STEP = 16
CAMERA_MODE_SETTLE_SECONDS = 3
BRIGHTNESS_FILTER_ALPHA = 0.2
# V52.6: slower brightness filter in NIGHT/LOW LIGHT before solar noon, so the dawn gain does not ping-pong.
DAWN_BRIGHTNESS_FILTER_ALPHA = 0.1
# V52.6: NIGHT exposure cap tapers from MAX_NIGHT to MAX_LOW_LIGHT between this elevation and NIGHT_ELEVATION at dawn.
NIGHT_DAWN_CAP_START_ELEVATION = -8.0
# V52.6: dawn LOW LIGHT keeps the locked NIGHT colour gains instead of re-running Auto AWB.
LOW_LIGHT_DAWN_AWB_LOCK = True
# V52.6: a timed-out control is resubmitted once and given this many more captures before reconciling.
CONTROL_ACK_RETRY_CAPTURES = 2
# V52.6: NIGHT frame quality labels (DARK uses NIGHT_OBSERVABILITY_MIN_BRIGHTNESS).
NIGHT_QUALITY_NOISY_GAIN = 3.2
NIGHT_QUALITY_WASH_BRIGHTNESS = 85.0
AWB_HISTORY_LENGTH = 20
AWB_MINIMUM_SAMPLES = 8
AWB_GAIN_MIN = 0.5
AWB_GAIN_MAX = 4.75
AWB_OUTLIER_FRACTION = 0.25
DAY_CONTRAST_WARNING = 20.0
TWILIGHT_CONTRAST_WARNING = 20.0
LOW_LIGHT_CONTRAST_WARNING = 10.0
NIGHT_CONTRAST_WARNING = 10.0
QUALITY_BASELINE_LENGTH = 360
QUALITY_BASELINE_MINIMUM_SAMPLES = 30
QUALITY_WARNING_RATIO = 0.7
QUALITY_CRITICAL_RATIO = 0.45
QUALITY_EDGE_THRESHOLD = 12.0
QUALITY_STATE_FILENAME = os.path.join(LOGS_PATH, 'camera_quality_state.json')
QUALITY_STATE_MAX_AGE_DAYS = 7
QUALITY_WARNING_CONSECUTIVE = 6
QUALITY_CRITICAL_CONSECUTIVE = 12
QUALITY_RECOVERY_RATIO = 0.8
QUALITY_RECOVERY_CONSECUTIVE = 6
QUALITY_MODE_SETTLE_CAPTURES = 6
QUALITY_FRESH_VALIDATION_SAMPLES = 12
QUALITY_STORED_BASELINE_MAX_ABOVE_FRESH = 1.35
QUALITY_BASELINE_MAX_ADAPT_FRACTION = 0.05
CONTROL_ACK_EXPOSURE_TOLERANCE_US = 50000
CONTROL_ACK_GAIN_TOLERANCE = 0.05
CONTROL_ACK_GAIN_TOLERANCE_FRACTION = 0.12
CONTROL_ACK_MAX_CAPTURES = 4
MODE_TRANSITION_MAX_EXPOSURE_CHANGE_FRACTION = 0.30
CONTROL_SUBMIT_EXPOSURE_THRESHOLD_US = 1000
CONTROL_SUBMIT_GAIN_THRESHOLD = 0.01
TIMELAPSE_FPS = 30
TIMELAPSE_CRF = 23
TIMELAPSE_PRESET = 'medium'
UPLOAD_TIMELAPSE = True
TIMELAPSE_START_HOUR = 0
TIMELAPSE_START_MINUTE = 5
TIMELAPSE_RETRY_MINUTES = 15
TIMELAPSE_MAX_ATTEMPTS = 8
TIMELAPSE_FFMPEG_TIMEOUT_SECONDS = 7200
FFMPEG_PROGRESS_LOG_INTERVAL_SECONDS = 60
TIMELAPSE_MIN_FILE_SIZE_BYTES = 1000000
PARTIAL_TIMELAPSE_MIN_FILE_SIZE_BYTES = 50000
HOURLY_TODAY_TIMELAPSE_ENABLED = True
HOURLY_TODAY_TIMELAPSE_MINUTE = 2
HOURLY_TODAY_TIMELAPSE_LOCAL_FILENAME = 'today_timelapse.mp4'
HOURLY_TODAY_TIMELAPSE_MIN_FRAMES = 30
HOURLY_TIMELAPSE_RETRY_MINUTES = 5
HOURLY_TIMELAPSE_MAX_ATTEMPTS = 3
LOG_ANOMALY_SUMMARY_ENABLED = True
LOG_ANOMALY_SUMMARY_INTERVAL_MINUTES = 60
LOG_ANOMALY_CPU_WARNING_C = 70.0
LOG_ANOMALY_CAPTURE_WARNING_MS = 1500.0
LOG_ANOMALY_FTP_FAILURE_WARNING = 1
V51_RELEASE = 'V52.6'
V50_FTP_WORKER_RESTART_COOLDOWN_SECONDS = 60
V50_MAX_CAMERA_RESTARTS_PER_HOUR = 6
V50_TELEMETRY_MAX_CLOCK_SKEW_SECONDS = 300
V50_ALERT_ACKNOWLEDGED_FILE = os.path.join(LOGS_PATH, 'incident_acknowledgements.json')
TIMELAPSE_MIN_FRAME_COMPLETENESS = 0.95
TIMELAPSE_SEGMENT_MANIFEST_SCHEMA = 1
TIMELAPSE_SEGMENT_MANIFEST_FILENAME = 'manifest.json'
TIMELAPSE_VIDEO_PROFILE = 'high'
TIMELAPSE_VIDEO_LEVEL = '5.1'
TIMELAPSE_GOP_SECONDS = 2
TIMELAPSE_GOP_FRAMES = TIMELAPSE_FPS * TIMELAPSE_GOP_SECONDS
TIMELAPSE_TRACK_TIMESCALE = 90000
TIMELAPSE_FPS_TOLERANCE = 0.05
TIMELAPSE_FFPROBE_TIMEOUT_SECONDS = 30
TIMELAPSE_CONCAT_TIMEOUT_SECONDS = 600
TIMELAPSE_TEMP_FILE_MAX_AGE_HOURS = 6
DAILY_TIMELAPSE_USE_SEGMENTS = True
DAILY_TIMELAPSE_FALLBACK_TO_FRAMES = True
FTP_SNAPSHOT_RETENTION_HOURS = 1
MAX_CONSECUTIVE_CAPTURE_FAILURES = 3
CAMERA_RESTART_DELAY_SECONDS = 3
CAMERA_RESTART_SETTLE_SECONDS = 5
LOG_INFO_ENABLED = True
LOG_DEBUG_ENABLED = False
APPLICATION_LOG_FILENAME = os.path.join(LOGS_PATH, 'weather_camera.log')
application_file_handler = TimedRotatingFileHandler(APPLICATION_LOG_FILENAME, when='midnight', interval=1, backupCount=APPLICATION_LOG_RETENTION_DAYS, encoding='utf-8', delay=True)
if LOG_DEBUG_ENABLED:
    LOG_LEVEL = logging.DEBUG
elif LOG_INFO_ENABLED:
    LOG_LEVEL = logging.INFO
else:
    LOG_LEVEL = logging.WARNING
console_handler = logging.StreamHandler()
console_handler.setLevel(LOG_LEVEL)
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
application_file_handler.setLevel(LOG_LEVEL)
application_file_handler.setFormatter(log_formatter)
console_handler.setFormatter(log_formatter)
logging.basicConfig(level=LOG_LEVEL, handlers=[application_file_handler, console_handler], force=True)
logger = logging.getLogger('harpenden_weather_camera')
logger.setLevel(LOG_LEVEL)
logger.propagate = True
service_start_time = datetime.now(HARPENDEN_TIMEZONE)
last_health_snapshot_time = None
health_snapshot_count = 0
health_snapshot_failure_count = 0
health_previous_process_rss_bytes = None
termination_signal = None
cached_sun_date = cached_sunrise = cached_sunset = None
current_operating_date = current_camera_mode = current_solar_elevation = None
mode_entered_time = None
mode_transition_count = 0
mode_last_duration_seconds = None
last_housekeeping_time = last_timelapse_scheduled_for = None
last_timelapse_completed_for = next_timelapse_retry_time = None
last_hourly_today_timelapse_slot = None
last_hourly_today_timelapse_completed_slot = None
hourly_today_timelapse_thread = None
hourly_today_timelapse_next_retry_time = None
hourly_today_timelapse_attempts = {}
timelapse_attempts = {}
consecutive_camera_acquisition_failures = 0
capture_count = camera_acquisition_failure_count = camera_restart_count = 0
camera_restart_times = deque(maxlen=V50_MAX_CAMERA_RESTARTS_PER_HOUR)
image_processing_failure_count = storage_failure_count = 0
telemetry_failure_count = status_failure_count = 0
ftp_image_success_count = ftp_status_success_count = ftp_failure_count = 0
ftp_consecutive_failures = 0
ftp_last_success_time = ftp_last_upload_ms = None
ftp_health_state = 'HEALTHY'
ftp_health_state_since = None
ftp_outage_started = None
ftp_recovery_successes = 0
ftp_outage_count = 0
ftp_recovery_count = 0
ftp_suppressed_warning_count = 0
ftp_last_failure_log_time = None
capture_processing_total_ms = capture_processing_max_ms = 0.0
last_controller_state_save_time = last_daily_summary_date = None
current_exposure_action = 'HOLD'
manual_exposure_us = manual_gain = filtered_brightness = None
night_colour_gains = None
awb_gain_history = deque(maxlen=AWB_HISTORY_LENGTH)
last_actual_exposure = last_actual_gain = None
exposure_action_history = deque(maxlen=8)
last_capture_time = None
daily_counter_baseline = {}
daily_counter_baseline_time = None
sharpness_history = {mode: deque(maxlen=QUALITY_BASELINE_LENGTH) for mode in ('DAY', 'TWILIGHT', 'LOW LIGHT', 'NIGHT')}
quality_warning_streak = 0
quality_critical_streak = 0
quality_recovery_streak = 0
quality_alert_level = None
quality_alert_started = None
quality_tracking_mode = None
day_fresh_sharpness_samples = []
day_baseline_validated = False
day_baseline_source = 'validating'
day_baseline_candidate = None
quality_mode_capture_count = 0
night_observability_open = False
night_observability_recovery_streak = 0
night_observability_failure_streak = 0
pending_control_captures = 0
control_ack_retry_used = False
night_quality_state = 'N/A'
mode_control_pending = False
mode_transition_target_exposure_us = None
low_light_entry_floor_product = None
low_light_floor_interventions = 0
timelapse_thread = None
daily_timelapse_lock = threading.Lock()
hourly_timelapse_lock = threading.Lock()
ffmpeg_lock = threading.Lock()
camera_lock = threading.RLock()
telemetry_lock = threading.Lock()
telemetry_schema_filename_cache = {}
audit_lock = threading.Lock()
segment_manifest_lock = threading.Lock()
shutdown_event = threading.Event()
web_upload_queue = queue.Queue(maxsize=1)
FTP_SNAPSHOT_PATH = os.path.join(LOGS_PATH, 'ftp_snapshot')
os.makedirs(FTP_SNAPSHOT_PATH, exist_ok=True)
ftp_thread = None
ftp_worker_restart_count = 0
ftp_worker_unexpected_stops = 0
ftp_worker_last_seen = None
ftp_worker_last_restart = None
last_timelapse_build_method = None
last_timelapse_segment_count = 0
last_timelapse_expected_frames = 0
last_timelapse_source_gaps = []
last_anomaly_summary_time = None
anomaly_window = {
    'capture_slow': 0,
    'cpu_hot': 0,
    'quality_warning': 0,
    'quality_critical': 0,
    'lens_degraded': 0,
    'exposure_limit': 0,
    'ftp_failures_start': 0,
    'camera_failures_start': 0,
    'storage_failures_start': 0,
    'processing_failures_start': 0,
    'telemetry_failures_start': 0,
    'status_failures_start': 0,
    'timelapse_gaps': 0,
    'max_capture_ms': 0.0,
    'max_cpu_c': None,
}

