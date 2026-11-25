from pathlib import Path
import ast
import importlib.util
import hashlib
import json
import logging
import os
import pytest
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from hws_testlib import ROOT, VERSION, NUM, load_source_module, load_v52_namespace, load_timelapse_functions, _load_dashboard, _camera_namespace, _dash


def test_telemetry_schema():
    tree = ast.parse((ROOT / 'publishing.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(getattr(target, 'id', '') == 'TELEMETRY_FIELDS' for target in node.targets):
                assert len(ast.literal_eval(node.value)) == 58
                return
    raise AssertionError('TELEMETRY_FIELDS not found')

def test_mode_performance_summary_and_sample_status():
    spec = importlib.util.spec_from_file_location(
        'weathercam_dashboard_source', ROOT / 'weathercam_dashboard/dashboard.py'
    )
    dashboard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dashboard)

    now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(11):
        rows.append({
            '_ts': now - timedelta(minutes=12 - i),
            'camera_mode': 'DAY',
            'image_quality_score': 80 + i,
            'sharpness_score': 50 + i,
            'brightness_raw': 100 + i,
            'exposure_ms': 10 + i,
            'analogue_gain': 1.5,
            'digital_gain': 1.0,
        })
    rows.extend([
        {
            '_ts': now - timedelta(minutes=1),
            'camera_mode': 'TWILIGHT',
            'image_quality_score': 60,
            'exposure_ms': 20,
        },
        {
            '_ts': now,
            'camera_mode': 'TWILIGHT',
            'image_quality_score': 70,
            'exposure_ms': 30,
        },
        {
            '_ts': now - timedelta(days=2),
            'camera_mode': 'NIGHT',
            'image_quality_score': 100,
        },
    ])
    rows.reverse()
    result = dashboard.mode_effectiveness(rows, now)
    assert result['modes']['DAY']['samples'] == 11
    assert result['modes']['DAY']['sample_status'] == 'SAMPLED'
    assert result['modes']['DAY']['quality'] == 85
    assert result['modes']['DAY']['duration_seconds'] == 660
    assert result['modes']['TWILIGHT']['samples'] == 2
    assert result['modes']['TWILIGHT']['sample_status'] == 'LIMITED'
    assert result['modes']['NIGHT']['sample_status'] == 'NO DATA'
    assert [item['mode'] for item in result['transitions']] == ['DAY', 'TWILIGHT']

def test_raspberry_pi_throttle_flags():
    monitoring = load_source_module('monitoring_source', ROOT / 'monitoring.py')
    expected = {
        0x1: 'under_voltage_now',
        0x2: 'frequency_capped_now',
        0x4: 'throttled_now',
        0x8: 'soft_temperature_limit_now',
        0x10000: 'under_voltage_occurred',
        0x20000: 'frequency_capping_occurred',
        0x40000: 'throttling_occurred',
        0x80000: 'soft_temperature_limit_occurred',
    }
    for bit, expected_field in expected.items():
        monitoring.subprocess = SimpleNamespace(
            run=lambda *args, _bit=bit, **kwargs: SimpleNamespace(
                returncode=0, stdout=f'throttled=0x{_bit:x}'
            ),
            TimeoutExpired=subprocess.TimeoutExpired,
        )
        flags = monitoring._read_pi_throttled()
        assert flags[expected_field]
        assert sum(bool(flags[field]) for field in expected.values()) == 1

def test_timelapse_completion_updates_daily_health_report(tmp_path):
    monitoring = load_source_module('monitoring_source', ROOT / 'monitoring.py')
    day = datetime(2026, 11, 19, tzinfo=timezone.utc).date()
    monitoring.os = os
    monitoring.json = json
    monitoring.LOGS_PATH = str(tmp_path)
    monitoring.TIMELAPSE_PATH = str(tmp_path)
    monitoring.last_timelapse_completed_for = day
    monitoring.last_timelapse_build_method = 'segment_concat'
    monitoring.last_timelapse_segment_count = 3
    monitoring.last_timelapse_expected_frames = 100
    monitoring.last_timelapse_source_gaps = []
    monitoring.local_now = lambda: datetime(2026, 11, 20, tzinfo=timezone.utc)
    report = tmp_path / 'daily_health_20261119.json'
    report.write_text(json.dumps({'date': day.isoformat(), 'capture_count': 8640}))

    assert monitoring.update_daily_summary_timelapse_status(day)
    updated = json.loads(report.read_text())
    assert updated['capture_count'] == 8640
    assert updated['timelapse_publish_complete'] is True
    assert not (tmp_path / 'daily_summary_20261119.json').exists()

def test_malformed_quality_state_is_rejected_without_crashing(tmp_path):
    state = load_source_module('state_source', ROOT / 'state.py')
    saved = datetime(2026, 11, 19, tzinfo=timezone.utc)
    filename = tmp_path / 'quality.json'
    filename.write_text(json.dumps({
        'saved': saved.isoformat(),
        'sharpness_history': [],
    }))
    state.QUALITY_STATE_FILENAME = str(filename)
    state.QUALITY_STATE_MAX_AGE_DAYS = 7
    state.QUALITY_STATE_SCHEMA_VERSION = 2
    state.HARPENDEN_TIMEZONE = timezone.utc
    state.local_now = lambda: saved
    state.datetime = datetime
    state.timedelta = timedelta
    state.json = json
    state.math = __import__('math')
    state.logger = logging.getLogger('test-state')
    state.sharpness_history = {mode: [] for mode in ('DAY', 'TWILIGHT', 'LOW LIGHT', 'NIGHT')}

    assert state.load_quality_state() is False

def test_controller_configuration_fingerprint_tracks_real_limits():
    source = (ROOT / 'controller_analytics.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == '_configuration_fingerprint'
    )
    namespace = {
        'hashlib': hashlib,
        'MAX_TWILIGHT_EXPOSURE_US': 1000000,
        'MAX_LOW_LIGHT_EXPOSURE_US': 1500000,
        'MAX_NIGHT_EXPOSURE_US': 4500000,
        'MIN_EXPOSURE_US': 1000,
        'MIN_ANALOGUE_GAIN': 1.0,
        'ABSOLUTE_MAX_GAIN': 4.0,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<fingerprint-test>', 'exec'), namespace)
    first = namespace['_configuration_fingerprint']()
    namespace['MAX_LOW_LIGHT_EXPOSURE_US'] = 1600000
    assert namespace['_configuration_fingerprint']() != first

def test_dashboard_selects_latest_timelapse_file(tmp_path):
    dashboard = load_source_module('dashboard_timelapse_source', ROOT / 'weathercam_dashboard/dashboard.py')
    directory = tmp_path / 'timelapse'
    directory.mkdir()
    older = directory / 'timelapse_20261117.mp4'
    latest = directory / 'timelapse_20261118.mp4'
    older.write_bytes(b'old')
    latest.write_bytes(b'latest-video')
    os.utime(older, (1000, 1000))
    os.utime(latest, (2000, 2000))
    dashboard.ROOT = tmp_path

    video = dashboard.latest_timelapse()

    assert video['filename'] == latest.name
    assert video['size_bytes'] == len(b'latest-video')

def test_dashboard_recommendations_cover_throttling_and_timelapse_gaps():
    dashboard = load_source_module('dashboard_recommendations_source', ROOT / 'weathercam_dashboard/dashboard.py')
    metrics = {
        'capture_state': 'HEALTHY', 'ftp_health': 'HEALTHY', 'control_health': 'HEALTHY',
        'disk_free_gb': 20, 'cpu_temp_c': 50, 'memory_percent': 40,
        'throttling_active': True, 'health_age_seconds': 60,
    }

    checks = dashboard.recommended_checks(metrics, {'source_gap_count': 2})

    assert {item['issue'] for item in checks} == {'Power or thermal throttling', 'Timelapse gaps'}
    assert all(item['action'] for item in checks)

def test_scene_cloud_cover_and_frozen_detection(tmp_path):
    import numpy as np
    scene = load_v52_namespace(tmp_path, 'scene_analysis.py')
    height, width = 100, 100
    clear = np.zeros((height, width, 3), dtype=np.float32)
    clear[:] = (60, 120, 220)
    cloudy = np.zeros((height, width, 3), dtype=np.float32)
    cloudy[:] = (200, 200, 200)
    assert scene['estimate_cloud_cover'](clear) < 10
    assert scene['estimate_cloud_cover'](cloudy) > 90
    assert scene['classify_cloud_cover'](5) == 'CLEAR' and scene['classify_cloud_cover'](95) == 'OVERCAST'
    frame = np.random.default_rng(1).integers(0, 255, (640, 640, 3), dtype=np.uint8)
    results = [scene['update_frozen_detection'](frame) for _ in range(scene['SCENE_FROZEN_CONSECUTIVE'] + 2)]
    assert results[-1] and not results[0]
    assert not scene['update_frozen_detection'](255 - frame)

def test_scene_blocked_view_and_weather_parsing(tmp_path):
    scene = load_v52_namespace(tmp_path, 'scene_analysis.py')
    uniform = {'contrast': 1.0, 'sharpness_score': 0.2}
    flags = [scene['update_blocked_detection'](uniform) for _ in range(scene['SCENE_BLOCKED_CONSECUTIVE'])]
    assert flags[-1] and not flags[0]
    scene['current_camera_mode'] = 'NIGHT'
    assert not scene['update_blocked_detection'](uniform)
    now = datetime.now(timezone.utc)
    fresh = {'updated': now.isoformat(), 'temperature_c': 12.5, 'humidity_percent': 140, 'wind_speed_mph': 8}
    parsed = scene['parse_weather_data'](fresh, now)
    assert parsed['temperature_c'] == 12.5 and 'humidity_percent' not in parsed
    stale = dict(fresh, updated=(now - timedelta(hours=2)).isoformat())
    assert scene['parse_weather_data'](stale, now) is None
    assert scene['parse_weather_data']('bad', now) is None

def test_keogram_slice_render_and_finalise(tmp_path):
    import numpy as np
    keogram = load_v52_namespace(tmp_path, 'keogram.py')
    image = np.zeros((3040, 4056, 3), dtype=np.uint8)
    image[:, :, 2] = 200
    start = datetime(2026, 11, 18, 6, 0, 0)
    for minute in range(60):
        assert keogram['record_keogram_slice'](image, start + timedelta(minutes=minute))
    assert not keogram['record_keogram_slice'](image, start + timedelta(minutes=59, seconds=10))
    raw = keogram['keogram_raw_filename'](start.date())
    assert os.path.getsize(raw) == 1440 * 360 * 3
    rendered = keogram['render_keogram_image'](raw)
    assert rendered.size == (1440, 360 + keogram['KEOGRAM_LABEL_HEIGHT'])
    uploads = []
    keogram['upload_to_ftp'] = lambda path, remote: uploads.append(remote) or True
    keogram['process_pending_keograms'](start.date() + timedelta(days=1))
    assert not os.path.exists(raw)
    assert os.path.exists(keogram['keogram_png_filename'](start.date()))
    assert uploads == ['keogram_20261118.png', 'latest_keogram.png']
    assert keogram['pending_keogram_days'](start.date() + timedelta(days=1)) == []

def test_periodic_timelapse_period_selection():
    source = (ROOT / 'timelapse.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'periodic_period')
    namespace = {'timedelta': timedelta, 'os': os, 'TIMELAPSE_PATH': '/t'}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<periodic>', 'exec'), namespace)
    first, last, name = namespace['periodic_period']('weekly', datetime(2026, 11, 19).date())
    assert (first.isoformat(), last.isoformat()) == ('2026-11-09', '2026-11-15')
    assert name.endswith('weekly_timelapse_20261109.mp4')
    first, last, name = namespace['periodic_period']('monthly', datetime(2026, 11, 19).date())
    assert (first.isoformat(), last.isoformat()) == ('2026-10-01', '2026-10-31')
    assert name.endswith('monthly_timelapse_202610.mp4')

def test_periodic_join_requires_compatible_inputs():
    namespace = load_timelapse_functions('periodic_inputs_compatible')
    check = namespace['periodic_inputs_compatible']
    good = {'codec_name': 'h264', 'width': 2560, 'height': 1440, 'pix_fmt': 'yuv420p'}
    assert check([good, dict(good)])
    assert not check([good, dict(good, width=1920, height=1080)])
    assert not check([good, dict(good, codec_name='hevc')])

def test_periodic_timelapse_retries_again_the_next_day():
    clock = [datetime(2026, 11, 20, 1, 0)]
    calls = []
    namespace = load_timelapse_functions(
        'process_periodic_timelapses', periodic_period=lambda kind, today: (datetime(2026, 11, 9).date(), None, None),
        periodic_timelapse_lock=__import__('threading').Lock(), periodic_timelapse_attempts={}, periodic_timelapse_next_retry={},
        PERIODIC_MAX_ATTEMPTS=3, PERIODIC_RETRY_MINUTES=30, local_now=lambda: clock[0],
        build_periodic_timelapse=lambda kind, today: calls.append((kind, today)) or False, set_periodic_status=lambda *a, **k: None)
    run = namespace['process_periodic_timelapses']
    for _ in range(6):
        clock[0] += timedelta(minutes=31)
        run(clock[0].date())
    assert len([c for c in calls if c[0] == 'weekly']) == 3
    clock[0] += timedelta(days=1)
    run(clock[0].date())
    assert len([c for c in calls if c[0] == 'weekly']) == 4

def test_dashboard_hour_falls_back_to_local_minutes(tmp_path):
    dashboard = load_source_module('dashboard_minute_source', ROOT / 'weathercam_dashboard/dashboard.py')
    dashboard.LD = tmp_path
    end = datetime.now(timezone.utc)
    samples = [{'t': (end - timedelta(minutes=m)).isoformat(), 'temperature_c': 5.0 + m, 'wind_speed_mph': 2.0} for m in (50, 40, 30, 10, 0)]
    (tmp_path / 'weather_station_minute.json').write_text(json.dumps({'samples': samples}))
    hour = dashboard.weather_hour()
    assert hour['source'] == 'local' and len(hour['temperature_c']) == 60
    assert hour['temperature_c'][59] == 5.0 and hour['temperature_c'][29] == 35.0 and hour['temperature_c'][0] is None

def test_overlay_station_extras(tmp_path):
    format_weather_overlay = load_v52_namespace(tmp_path, 'scene_analysis.py')['format_weather_overlay']
    text = format_weather_overlay({'temperature_c': 5, 'wind_gust_mph': 20, 'solar_radiation_wm2': 300, 'uv_index': 1.5})
    assert 'Gust 20mph' in text and 'Solar 300W/m2' in text and 'UV 1.5' in text
    assert 'Solar' not in format_weather_overlay({'temperature_c': 5, 'solar_radiation_wm2': 0})

def test_periodic_upload_switches_are_per_kind():
    timelapse = (ROOT / 'timelapse.py').read_text(encoding='utf-8')
    core = (ROOT / 'core.py').read_text(encoding='utf-8')
    assert "HWS_UPLOAD_WEEKLY_TIMELAPSE" in core and "HWS_UPLOAD_MONTHLY_TIMELAPSE" in core
    assert "upload = UPLOAD_TIMELAPSE and (UPLOAD_WEEKLY_TIMELAPSE if kind == 'weekly' else UPLOAD_MONTHLY_TIMELAPSE)" in timelapse
    assert "    if upload:\n        if not (upload_to_ftp(output" in timelapse

def test_night_long_exposure_does_not_flag_lens_degraded():
    source = (ROOT / 'image_quality.py').read_text(encoding='utf-8')
    assert "current_camera_mode == 'NIGHT' and (manual_exposure_us or 0) > NIGHT_LENS_TOLERANT_EXPOSURE_US" in source
    assert "lens_status = 'POSSIBLE OBSTRUCTION'" in source

def test_scene_analysis_marks_night_as_paused(tmp_path):
    import numpy as np
    scene = load_v52_namespace(tmp_path, 'scene_analysis.py')
    scene['current_camera_mode'] = 'NIGHT'
    scene['METERING_STEP'] = 16
    image = np.full((100, 100, 3), 20, dtype=np.uint8)
    result = scene['update_scene_analysis'](image, {'contrast': 10.0, 'brightness': 20.0})
    assert result['analysis_paused'] is True and result['mode'] == 'NIGHT'
    assert 'Paused' in (ROOT / 'weathercam_dashboard/templates/dashboard.html').read_text(encoding='utf-8')

def test_uniform_overcast_sky_reads_full_cloud(tmp_path):
    import numpy as np
    scene = load_v52_namespace(tmp_path, 'scene_analysis.py')
    rng = np.random.default_rng(2)
    overcast = np.zeros((100, 100, 3), dtype=np.float32)
    overcast[:] = (110, 125, 150)
    overcast += rng.normal(0, 2, overcast.shape).astype(np.float32)
    assert scene['estimate_cloud_cover'](overcast) == 100.0

def test_pale_blue_gap_in_cloud_is_not_full_overcast(tmp_path):
    import numpy as np
    scene = load_v52_namespace(tmp_path, 'scene_analysis.py')
    sky = np.zeros((100, 100, 3), dtype=np.float32)
    sky[:] = (157, 162, 171)
    sky[40:60] = (142, 177, 197)
    assert 10 < scene['estimate_cloud_cover'](sky) < 90

def test_ack_gain_tolerance_scales_with_gain():
    core = (ROOT / 'core.py').read_text(encoding='utf-8')
    assert 'CONTROL_ACK_GAIN_TOLERANCE_FRACTION = 0.12' in core
    assert 'CONTROL_ACK_GAIN_TOLERANCE_FRACTION' in (ROOT / 'exposure.py').read_text(encoding='utf-8')
    assert 'CONTROL_ACK_GAIN_TOLERANCE_FRACTION' in (ROOT / 'v47_control.py').read_text(encoding='utf-8')

def test_dashboard_scene_recommendations():
    dashboard = load_source_module('dashboard_scene_source', ROOT / 'weathercam_dashboard/dashboard.py')
    metrics = {
        'capture_state': 'OK', 'ftp_health': 'OK', 'control_health': 'OK', 'disk_free_gb': 50,
        'cpu_temp_c': 40, 'memory_percent': 20, 'throttling_active': False, 'health_age_seconds': 10,
    }
    checks = dashboard.recommended_checks(metrics, None, {'alerts': ['FROZEN_IMAGE', 'LENS_DROPLETS']})
    assert [item['issue'] for item in checks] == ['Frozen image', 'Lens droplets']
    assert dashboard.recommended_checks(metrics, None) == []

def test_dashboard_mode_schedule_matches_real_dawn(tmp_path, monkeypatch):
    dash = _load_dashboard(tmp_path, monkeypatch)
    now = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)
    schedule = dash.mode_schedule(now, back_hours=1, forward_hours=3)
    assert [(s['from'], s['to']) for s in schedule] == [('NIGHT', 'LOW LIGHT'), ('LOW LIGHT', 'TWILIGHT'), ('TWILIGHT', 'DAY')]
    first = datetime.fromisoformat(schedule[0]['time'])
    assert abs((first - datetime(2026, 11, 20, 6, 59, tzinfo=timezone.utc)).total_seconds()) <= 300
    upcoming = dash.next_mode_change(now, schedule)
    assert upcoming['to'] == 'LOW LIGHT' and upcoming['minutes'] > 0

def test_night_exposure_cap_tapers_at_dawn_only(tmp_path):
    ns = _camera_namespace(tmp_path)
    cap = ns['maximum_exposure_for_mode']
    assert cap('NIGHT') == 4500000
    ns['current_solar_elevation'] = -6.5
    assert 1500000 < cap('NIGHT') < 4500000
    ns['current_solar_elevation'] = -5.0
    assert cap('NIGHT') == 1500000
    ns['local_now'] = lambda: datetime(2026, 11, 20, 20, 0).astimezone()
    assert cap('NIGHT') == 4500000
    assert cap('LOW LIGHT') == 1500000

def test_dawn_filter_is_slower_and_night_quality_labels(tmp_path):
    ns = _camera_namespace(tmp_path, current_camera_mode='NIGHT')
    assert ns['brightness_filter_alpha']() == 0.1
    ns['local_now'] = lambda: datetime(2026, 11, 20, 20, 0).astimezone()
    assert ns['brightness_filter_alpha']() == 0.2
    classify = ns['classify_night_quality']
    assert classify({}, 40.0, 0.5) == 'GOOD'
    assert classify({}, 10.0, 0.0) == 'DARK'
    assert classify({}, 90.0, 0.0) == 'WASHED'
    ns['manual_gain'] = 3.5
    assert classify({}, 40.0, 0.5) == 'NOISY'

def test_dawn_low_light_locks_night_colour_gains(tmp_path):
    from types import SimpleNamespace
    controls = SimpleNamespace(AwbModeEnum=SimpleNamespace(Auto=1))
    ns = _camera_namespace(tmp_path, controls=controls, current_camera_mode='LOW LIGHT', night_colour_gains=(1.9, 1.4),
        LOW_LIGHT_DAWN_AWB_LOCK=True, manual_exposure_us=500000, mode_control_pending=False, DAY_CAMERA_CONTROLS={},
        MIN_EXPOSURE_US=1000, MIN_ANALOGUE_GAIN=1.0, ABSOLUTE_MAX_GAIN=4.0, LOW_LIGHT_SHARPNESS=1.0, TWILIGHT_SHARPNESS=1.0,
        NIGHT_SHARPNESS=1.0, NIGHT_INITIAL_EXPOSURE_US=80000, LOW_LIGHT_INITIAL_EXPOSURE_US=80000, INITIAL_LOW_LIGHT_GAIN=1.4)
    locked = ns['build_camera_controls']('LOW LIGHT')
    assert locked['AwbEnable'] is False and locked['ColourGains'] == (1.9, 1.4)
    ns['local_now'] = lambda: datetime(2026, 11, 20, 20, 0).astimezone()
    assert ns['build_camera_controls']('LOW LIGHT')['AwbEnable'] is True

def test_control_ack_retry_is_wired_before_reconcile():
    source = (ROOT / 'exposure.py').read_text(encoding='utf-8')
    assert source.index('[CONTROL ACK] RETRY') < source.index('[CONTROL ACK] TIMEOUT')
    assert source.count('control_ack_retry_used = False') >= 3

def test_low_sun_cloud_cover_ignores_warm_clear_sky(tmp_path):
    import numpy as np
    ns = load_v52_namespace(tmp_path, 'scene_analysis.py')
    rng = np.random.default_rng(1)
    rows = np.linspace(0.65, 1.15, 112)[:, None]
    ratio = rows + rng.normal(0, 0.01, (112, 200))
    sky = np.zeros((112, 200, 3), np.float32)
    sky[:, :, 2] = 150
    sky[:, :, 0] = 150 * ratio
    sky[:, :, 1] = 150
    assert ns['estimate_cloud_cover'](sky) > 20
    assert ns['estimate_cloud_cover'](sky, low_sun=True) < 5
    sky[10:40, 50:150, 0] = 150
    assert ns['estimate_cloud_cover'](sky, low_sun=True) > 10

def test_lens_maintenance_learning_and_worsening(tmp_path):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)
    assert dash.lens_maintenance([], [], now)['status'] == 'LEARNING'
    tele = []
    for day in range(14):
        base = now - timedelta(days=13 - day)
        for minute in range(30):
            tele.append({'_ts': base.replace(hour=11) + timedelta(minutes=minute), 'camera_mode': 'DAY',
                         'image_quality_score': str(90 - day * 1.5), 'sharpness_score': str(60 - day * 2)})
    result = dash.lens_maintenance([], tele, now)
    assert result['status'] in ('CLEAN', 'WATCH') and result['days_worsening'] > 0

def test_sensor_graphs_fall_back_to_daily_history_when_scene_samples_are_missing(tmp_path):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    local_daily = {
        '2026-11-20': {
            'temp_avg_c': 9.5, 'dew_min_c': 2.0, 'dew_max_c': 6.0,
            'humidity_avg': 75, 'humidity_min': 65, 'humidity_max': 80,
            'pressure_avg_hpa': 1012, 'pressure_min_hpa': 1008, 'pressure_max_hpa': 1015,
            'wind_avg_mph': 3.5, 'wind_gust_mph': 18, 'rain_max_mm_h': 0.4,
            'rain_mm': 2.0, 'solar_max_wm2': 350,
            'cpu_load_avg': 45, 'uptime_last': 8, 'storage_usage_avg': 36,
            'ram_usage_avg': 42, 'power_consumption_avg': 3.1, 'process_count_avg': 95,
            'data_age_avg': 30, 'voltage_avg': 5.1, 'current_avg': 0.5,
            'signal_min': 40, 'signal_max': 70, 'base_board_temp_avg_c': 34,
            'rf_board_temp_avg_c': 38,
            'ground_temp_avg_c': 7.5, 'soil_wetness_avg_cbar': 68,
            'soil_temp_avg_c': 10.2, 'greenhouse_temp_avg_c': 14.1,
        },
        '2026-11-22': {
            'temp_avg_c': 10.5, 'dew_min_c': 3.0, 'dew_max_c': 7.0,
            'humidity_avg': 72, 'humidity_min': 62, 'humidity_max': 78,
            'pressure_avg_hpa': 1013, 'pressure_min_hpa': 1009, 'pressure_max_hpa': 1016,
            'wind_avg_mph': 4.0, 'wind_gust_mph': 20, 'rain_max_mm_h': 1.2,
            'rain_mm': 0.5, 'solar_max_wm2': 500,
            'cpu_load_avg': 48, 'uptime_last': 10, 'storage_usage_avg': 37,
            'ram_usage_avg': 43, 'power_consumption_avg': 3.2, 'process_count_avg': 96,
            'data_age_avg': 32, 'voltage_avg': 5.0, 'current_avg': 0.6,
            'signal_min': 42, 'signal_max': 72, 'base_board_temp_avg_c': 35,
            'rf_board_temp_avg_c': 39,
            'ground_temp_avg_c': 8.0, 'soil_wetness_avg_cbar': 72,
            'soil_temp_avg_c': 11.0, 'greenhouse_temp_avg_c': 15.3,
        },
    }
    series = [
        {'t': (now - timedelta(minutes=5)).isoformat(), 'ground_temperature_c': 6.0,
         'soil_wetness_cbar': 65, 'soil_temperature_c': 9.0, 'greenhouse_temperature_c': 13.0},
        {'t': now.isoformat(), 'ground_temperature_c': 7.0,
         'soil_wetness_cbar': 67, 'soil_temperature_c': 10.0, 'greenhouse_temperature_c': 14.0},
    ]
    graphs = dash.graph_data(now, series, [], {}, local_daily=local_daily)
    expected = {
        'temperature_c': [9.5, 10.5], 'dew_point_c': [4.0, 5.0],
        'humidity_percent': [75, 72], 'pressure_hpa': [1012, 1013],
        'wind_speed_mph': [3.5, 4.0], 'wind_gust_mph': [18, 20],
        'rain_rate_mm_h': [0.4, 1.2], 'rain_today_mm': [2.0, 0.5],
        'solar_radiation_wm2': [350, 500],
        'ground_temperature_c': [7.5, 8.0],
        'soil_wetness_cbar': [68, 72],
        'soil_temperature_c': [10.2, 11.0],
        'greenhouse_temperature_c': [14.1, 15.3],
        'cpu_load_percent': [45, 48], 'bridge_uptime_hours': [8, 10],
        'storage_usage_percent': [36, 37], 'ram_usage_percent': [42, 43],
        'power_consumption_w': [3.1, 3.2], 'process_count': [95, 96],
        'bridge_data_age_s': [30, 32], 'voltage_v': [5.1, 5.0],
        'current_a': [0.5, 0.6], 'signal_min': [40, 42], 'signal_max': [70, 72],
        'base_board_temperature_c': [34, 35], 'rf_board_temperature_c': [38, 39],
    }
    for period in ('7d', 'month'):
        assert graphs[period]['daily_fallback_used'] is True
        assert set(graphs[period]['daily_fallback_fields'].split(',')) == set(expected)
        assert len(graphs[period]['t']) == 2
        for field, values in expected.items():
            assert graphs[period][field] == values
    for field in expected:
        assert len(graphs['24h'][field]) == 2
    for row, day in zip(graphs['daily'], local_daily.values()):
        assert row['ground_temp_avg_c'] == day['ground_temp_avg_c']
        assert row['greenhouse_temp_avg_c'] == day['greenhouse_temp_avg_c']

def test_sensor_graphs_prefer_detailed_scene_samples_over_daily_fallback(tmp_path):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    scene = [
        {'t': now - timedelta(days=2), 'ground_temperature_c': 5.0},
        {'t': now - timedelta(days=1), 'ground_temperature_c': 6.0},
    ]
    graphs = dash.graph_data(now, [], scene, {}, local_daily={
        '2026-11-20': {'ground_temp_avg_c': 17.0, 'greenhouse_temp_avg_c': 13.0},
        '2026-11-22': {'ground_temp_avg_c': 18.0, 'greenhouse_temp_avg_c': 14.0},
    })
    for period in ('7d', 'month'):
        assert graphs[period]['daily_fallback_used'] is True
        assert [v for v in graphs[period]['ground_temperature_c'] if v is not None] == [5.0, 6.0]
        assert [v for v in graphs[period]['greenhouse_temperature_c'] if v is not None] == [13.0, 14.0]

def test_shared_site_layout_keogram_and_live_snapshot(tmp_path, monkeypatch):
    import re
    dash = _dash(tmp_path)
    monkeypatch.setattr(dash, 'OUT', tmp_path / 'out')
    monkeypatch.setattr(dash, 'ROOT', tmp_path)
    dash.OUT.mkdir()
    (dash.OUT / 'data.html').write_text('Retired page')
    (dash.OUT / 'weather-live.json').write_text('{"updated":"existing"}')
    (tmp_path / 'keogram').mkdir()
    (tmp_path / 'keogram' / 'keogram_20261122.png').write_bytes(b'keogram')
    weather = {'updated': datetime.now(timezone.utc).isoformat(), 'temperature_c': 8.5}
    (tmp_path / 'weather_station.json').write_text(json.dumps(weather))
    dash.generate(False)
    assert dash.sync_keogram()['date'] == '2026-11-22'
    assert dash.sync_keogram_archive()[0]['date'] == '2026-11-22'
    for name, label in dash.SITE_PAGES:
        page = (dash.OUT / name).read_text()
        nav = re.search(r'<nav class="hws-nav".*?</nav>', page).group()
        assert nav.replace(' aria-current="page"', '') == dash.SITE_NAV
        if name != 'health.html':  # HWS Health is linked from the logo, not the menu
            assert f'href="{name}" aria-current="page"' in nav
        assert f'<title>Harpenden Weather Station - {label}</title>' in page
        assert 'class="hws-logo"' in page and page.count('id="hws-foot"') == 1
        assert page.index('private automatic weather station') < page.index('&copy; 2026')
        assert '<a href="donate.html">donation page</a>' in page
        assert '</p><p class="hws-disclaimer">If you have found this site useful' in page
    assert not (dash.OUT / 'data.html').exists()
    assert '<h2>More</h2>' not in (dash.OUT / 'indexnew.html').read_text()
    assert 'function station()' in (dash.OUT / 'about.html').read_text()
    health = (dash.OUT / 'health.html').read_text()
    assert 'id="piStats"' in health and 'id="bridgeChecks"' in health
    assert json.loads((dash.OUT / 'weather-live.json').read_text()) == {'updated': 'existing'}
    assert json.loads((dash.OUT / 'dashboard-data.json').read_text())['weather']['temperature_c'] == 8.5
    for name in ('health.html', 'webcamhealth.html', 'mbhealth.html', 'pihealth.html'):
        page = (dash.OUT / name).read_text()
        main_nav = re.search(r'<nav class="hws-nav".*?</nav>', page).group()
        assert main_nav.replace(' aria-current="page"', '') == dash.SITE_NAV
        assert 'aria-current' not in main_nav  # HWS Health is reached from the logo
        nav = re.search(r'<nav id="viewNav".*?</nav>', page).group()
        assert re.findall(r'>([^<>]+)</(?:label|a)>', nav) == [
            'Current', 'Trends', 'Events', 'Advanced', 'Reports', 'Archive', 'Weather', 'Insights',
            'Webcam Health', 'Meteobridge', 'Pi Health',
        ]
        assert 'HWS Health' not in nav
        for key, label in dash.HEALTH_VIEWS:
            assert (f'for="view-{key}"' if name == 'health.html' else f'href="health.html#{key}"') in nav
        for href, _ in dash.HEALTH_PAGES:
            assert f'href="{href}"' in nav
        if name != 'health.html':
            assert f'href="{name}" aria-current="page"' in nav
    assert 'src="/Weather34/index.php"' in (dash.OUT / 'weather34.html').read_text()
    radar = (dash.OUT / 'radar.html').read_text()
    assert radar.count('>Rain Radar</a>') == radar.count('>Satellite</a>') == 1
    assert "win('wind')" in radar
    assert 'href="radar.html#wind"' in (dash.OUT / 'satellite.html').read_text()

def test_browser_weather_refresh_fallback_and_monotonic_dates():
    import shutil
    import pytest
    if not shutil.which('node'):
        pytest.skip('Node is required for the browser helper regression')
    script = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const timers=[],images=[
 {url:'latest.jpg',getAttribute(){return this.url},set src(value){this.url=value}},
 {url:'banner.jpg',getAttribute(){return this.url},set src(value){this.url=value}}
];
const context={console,Date,Intl,Number,Error,URL,location:{href:'https://example.test/'},addEventListener(){},localStorage:{getItem(){return null}},
 document:{documentElement:{dataset:{}},hidden:false,querySelectorAll(){return images},addEventListener(){}},
 window:{setInterval(fn,delay){timers.push({fn,delay})}},fetch:null};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const H=context.window.HWS;
assert.equal(timers[0].delay,10000);timers[0].fn();assert.match(images[0].url,/latest\.jpg\?ts=/);assert.equal(images[1].url,'banner.jpg');
assert.equal(H.date('20261122'),'22 Nov 2026');
assert.equal(H.date('2026-11-22'),'22 Nov 2026');
assert.equal(H.date('broken'),'Date unavailable');
const months=H.rainfallMonths([{d:'2024-01-01',v:1},{d:'2024-01-31',v:2},{d:'2024-02-01',v:0},{d:'2025-01-01',v:100}], '2024');
assert.equal(months.length,12);assert.equal(months[0][1],3);assert.equal(months[1][1],0);assert.equal(months[2][1],null);
const stale=H.weatherStatus({updated:new Date(Date.now()-11*60000).toISOString()},false);
assert.match(stale.warning,/stale/);assert.match(stale.last,/11 min ago/);
assert.match(H.weatherStatus({},false).warning,/No weather data/);
assert.match(H.weatherStatus({updated:new Date().toISOString()},true).warning,/refresh failed/);
(async()=>{
 const old={updated:'2026-01-01T00:00:00Z',temperature_c:1},fresh={updated:new Date().toISOString(),temperature_c:9};
 const calls=[];
 context.fetch=async(url,opts)=>{calls.push(url);assert.equal(opts.cache,'no-store');return {ok:!url.startsWith('weather-live'),status:404,json:async()=>({weather:fresh})}};
 assert.equal((await H.refreshWeather(old)).temperature_c,9);
 assert.equal(calls.length,2);
 context.fetch=async()=>({ok:true,json:async()=>old});
 assert.equal((await H.refreshWeather(fresh)).temperature_c,9);
 context.fetch=async()=>({ok:false,status:503});
 await assert.rejects(()=>H.refreshWeather(old),/Weather data unavailable/);
 context.fetch=async()=>({ok:true,json:async()=>({})});
 await assert.rejects(()=>H.refreshWeather(old),/Weather data unavailable.*no valid timestamp/);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    subprocess.run(['node', '-e', script, str(ROOT / 'weathercam_dashboard/templates/site.js')], check=True)

def test_sun_highlight_frame_selection():
    source = (ROOT / 'timelapse.py').read_text(encoding='utf-8')
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'select_highlight_frames')
    namespace = {'datetime': datetime, 'timedelta': __import__('datetime').timedelta, 'os': os}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<hl>', 'exec'), namespace)
    frames = [f'/f/frame_20261122_{h:02d}{m:02d}00.jpg' for h in range(6, 10) for m in range(0, 60)]
    chosen = namespace['select_highlight_frames'](frames, datetime(2026, 11, 22, 8, 0), 30)
    assert chosen[0].endswith('073000.jpg') and chosen[-1].endswith('083000.jpg') and len(chosen) == 61
    assert len(namespace['select_highlight_frames'](frames, datetime(2026, 11, 22, 8, 0), 120, limit=50)) == 50

def test_meteobridge_headers_fall_back_to_environment(monkeypatch):
    import weather_station as ws
    monkeypatch.setattr(ws, 'METEOBRIDGE_PASSWORD', '')
    monkeypatch.setenv('HWS_METEOBRIDGE_PASSWORD', 'pw')
    monkeypatch.setenv('HWS_METEOBRIDGE_USER', 'bob')
    assert ws._meteobridge_headers()['Authorization'].startswith('Basic ')
