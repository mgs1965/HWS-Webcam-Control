#!/usr/bin/env python3
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
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
VERSION = re.search(r'VERSION="(V[\d.]+)"', (ROOT / 'version.py').read_text(encoding='utf-8')).group(1)
NUM = VERSION[1:]

def test_release_identity():
    namespace = {}
    exec((ROOT / 'version.py').read_text(encoding='utf-8'), namespace)
    assert namespace['VERSION'] == VERSION
    assert namespace['TELEMETRY_SCHEMA_VERSION'] == 4

def test_telemetry_schema():
    tree = ast.parse((ROOT / 'publishing.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(getattr(target, 'id', '') == 'TELEMETRY_FIELDS' for target in node.targets):
                assert len(ast.literal_eval(node.value)) == 58
                return
    raise AssertionError('TELEMETRY_FIELDS not found')

def test_credentials_are_not_embedded():
    core = (ROOT / 'core.py').read_text(encoding='utf-8')
    assert "FTP_PASSWORD = os.getenv('HWS_FTP_PASSWORD', '')" in core
    assert 'cGnRUCGhc' not in core

def test_dashboard_payload():
    dashboard = (ROOT / 'weathercam_dashboard/dashboard.py').read_text(encoding='utf-8')
    template = (ROOT / 'weathercam_dashboard/templates/dashboard.html').read_text(encoding='utf-8')
    assert f"V='{NUM}'" in dashboard
    assert f"'release':'{VERSION}'" in dashboard
    assert "('month',None)" in dashboard
    assert 'incidents' in dashboard
    assert "'process_memory':('health','memory.process_rss_bytes',1/1048576)" in dashboard
    assert 'V49.11.2' not in template
    assert 'data-view="gallery"' not in template
    for view in ('live', 'trends', 'events', 'advanced', 'reports', 'archive'):
        assert f'id="{view}"' in template
    assert 'Diagnostics</button>' not in template
    assert 'data-view="controller"' not in template
    for period in ('24h', '7d', 'month'):
        assert f'data-period="{period}"' in template
    assert 'id="processMemoryChart"' in template
    assert 'id="trendCharts"' in template
    assert "D.series?.[period]?.[key]" in template
    assert template.count('__DATA__') == 1
    assert "dataText.startsWith('{')?JSON.parse(dataText):{}" in template
    assert "template.replace('__DATA__'" in dashboard
    assert "template.count('__DATA__') != 1:raise RuntimeError" in dashboard
    for view in ('live', 'trends', 'events', 'advanced', 'reports', 'archive'):
        assert f'id="view-{view}"' in template
    assert '__HEALTH_NAV__' in template
    assert '#view-live:checked~.page #live' in template
    assert '#view-trends:checked~.page #trends' in template
    assert '#view-reports:checked~.page #reports' in template
    assert '#view-archive:checked~.page #archive' in template
    assert template.index('id="view-live"') < template.index('<div class="page">')
    assert "document.querySelectorAll('.view-select')" in template
    assert 'Last 24 hours' in template
    assert 'Last 7 Days' in template
    assert 'This Calendar Month' in template
    assert 'Recent events' in template
    assert 'Raspberry Pi status' in template
    assert 'id="piStats"' in template
    assert "'cpu_load_percent'" in dashboard
    assert "'mode_performance':mode_effectiveness(telemetry_rows,now)" in dashboard
    assert 'id="modePerformanceRows"' in template
    assert 'id="modeTransitions"' in template
    assert 'renderModePerformance();' in template
    for chart in ('cpuTemperatureChart', 'cpuLoadChart', 'systemMemoryChart', 'diskUsedChart', 'throttlingChart', 'captureCompletenessChart'):
        assert f'id="{chart}"' in template
    assert 'id="timelapseStats"' in template
    assert 'id="recommendations"' in template
    assert 'id="galleryGrid"' in template
    assert 'Export this period as CSV' in template
    assert 'Export daily reports as CSV' in template
    assert "'coverage':chart_coverage" in dashboard
    assert "'timeline_events':timeline_events" in dashboard
    assert 'older_index%5==0' in dashboard

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

def load_source_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

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

def test_camera_service_unit_and_install_preserve_existing_unit():
    service = (ROOT / 'systemd/weathercam.service').read_text(encoding='utf-8')
    installer = (ROOT / 'install.sh').read_text(encoding='utf-8')
    assert 'EnvironmentFile=/etc/weathercam/dashboard.env' in service
    assert 'Restart=on-failure' in service
    assert 'TimeoutStopSec=240' in service
    assert 'systemctl cat weathercam.service' in installer
    assert 'weathercam.service" /etc/systemd/system/weathercam.service' in installer
    assert 'refusing to overwrite it' in installer

def test_dashboard_daily_reports_ignore_malformed_files(tmp_path):
    dashboard = load_source_module('dashboard_reports_source', ROOT / 'weathercam_dashboard/dashboard.py')
    dashboard.LD = tmp_path
    (tmp_path / 'daily_health_20261118.json').write_text('{"date":"2026-11-18","captures":900}')
    (tmp_path / 'daily_health_20261119.json').write_text('{malformed')

    reports = dashboard.daily_health_reports()

    assert len(reports) == 1
    assert reports[0]['date'] == '2026-11-18'
    assert reports[0]['captures'] == 900

def test_dashboard_sample_coverage_uses_valid_readings():
    dashboard = load_source_module('dashboard_coverage_source', ROOT / 'weathercam_dashboard/dashboard.py')
    start = datetime.now(timezone.utc)
    rows = [
        {'_ts': start, 'cpu': 42},
        {'_ts': start + timedelta(minutes=5), 'cpu': None},
        {'_ts': start + timedelta(minutes=10), 'cpu': 56},
    ]

    coverage = dashboard.sample_coverage(rows, 'cpu')

    assert coverage['samples'] == 2
    assert coverage['first'] == start.isoformat()
    assert coverage['last'] == (start + timedelta(minutes=10)).isoformat()

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

def test_dashboard_telemetry_sampling_preserves_30_day_span(tmp_path):
    dashboard = load_source_module('dashboard_telemetry_source', ROOT / 'weathercam_dashboard/dashboard.py')
    dashboard.TD = tmp_path
    filename = tmp_path / 'camera_telemetry_v4_202611.csv'
    start = datetime.now(timezone.utc) - timedelta(days=30)
    with filename.open('w', encoding='utf-8', newline='') as output:
        output.write('capture_time,brightness_raw\n')
        for index in range(121):
            output.write(f'{(start + timedelta(hours=6 * index)).isoformat()},{index}\n')

    rows = dashboard.telemetry()

    assert rows
    assert rows[-1]['_ts'] - rows[0]['_ts'] > timedelta(days=28)
    assert len(rows) < 121


def load_v52_namespace(tmp_path, *filenames):
    import glob, math, threading, time
    from collections import deque
    import numpy as np
    from PIL import Image, ImageDraw
    namespace = {
        'np': np, 'os': os, 'json': json, 'glob': glob, 'math': math, 'time': time,
        'threading': threading, 'deque': deque, 'datetime': datetime, 'timedelta': timedelta,
        'Image': Image, 'ImageDraw': ImageDraw, 'logger': logging.getLogger('v52-test'),
        'local_now': lambda: datetime.now().astimezone(), 'audit_event': lambda *a, **k: None,
        'clamp': lambda value, low, high: max(low, min(high, value)),
        'LOGS_PATH': str(tmp_path / 'logs'), 'LOCAL_SAVE_PATH': str(tmp_path),
        'WEB_WIDTH': 1920, 'WEB_HEIGHT': 1080, 'current_camera_mode': 'DAY',
        'upload_to_ftp': lambda *a, **k: True,
    }
    os.makedirs(namespace['LOGS_PATH'], exist_ok=True)
    for filename in filenames:
        exec(compile((ROOT / filename).read_text(encoding='utf-8'), filename, 'exec'), namespace)
    return namespace

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

def load_timelapse_functions(*names, **extra):
    tree = ast.parse((ROOT / 'timelapse.py').read_text(encoding='utf-8'))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    import threading
    namespace = {'timedelta': timedelta, 'os': os, 'threading': threading, 'logger': logging.getLogger('v52-test'), 'audit_event': lambda *a, **k: None}
    namespace.update(extra)
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<periodic>', 'exec'), namespace)
    return namespace

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

def test_weather_fog_risk(tmp_path):
    scene = load_v52_namespace(tmp_path, 'scene_analysis.py')
    risk = scene['weather_fog_risk']
    assert risk({'temperature_c': 5.6, 'dew_point_c': 5.0, 'humidity_percent': 97}) == 'HIGH'
    assert risk({'temperature_c': 5.6, 'dew_point_c': 3.6, 'humidity_percent': 91}) == 'MODERATE'
    assert risk({'temperature_c': 15.0, 'dew_point_c': 5.0, 'humidity_percent': 50}) == 'LOW'
    assert risk({'temperature_c': 5.0, 'humidity_percent': 100}) == 'HIGH'
    assert risk({'temperature_c': 5.0}) is None and risk(None) is None


def test_dashboard_weather_history_and_insight(tmp_path):
    dashboard = load_source_module('dashboard_weather_source', ROOT / 'weathercam_dashboard/dashboard.py')
    dashboard.LD = tmp_path
    now = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)
    assert dashboard.weather_history() is None
    (tmp_path / 'weather_station_history.json').write_text('{"daily":[{"date":"2026-11-19","temp_max_c":9.1}]}')
    assert dashboard.weather_history()['daily'][0]['temp_max_c'] == 9.1
    (tmp_path / 'scene').mkdir()
    rows = [{'timestamp': (now - timedelta(hours=h)).isoformat(), 'humidity_percent': 80 + h, 'fog_index': None} for h in (30, 3, 1)]
    (tmp_path / 'scene' / 'scene_20261120.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\nnot json\n')
    history = dashboard.scene_history(now)
    assert [p['humidity_percent'] for p in history] == [83.0, 81.0]
    weather = {'humidity_percent': 96, 'temperature_c': 5.6, 'dew_point_c': 5.0, 'temp_change_1h_c': -3.4, 'rain_rate_mm_h': 1.2}
    reasons = dashboard.weather_insight(weather, {'fog_risk': 'HIGH'})
    assert len(reasons) == 3 and 'Fog risk high' in reasons[0]
    assert dashboard.weather_insight(None, None) == []
    lightning = dashboard.weather_insight({'lightning_strikes_last_min': 2, 'wind_gust_max_today_mph': 30}, None)
    assert any('Lightning' in r for r in lightning) and any('Gusts' in r for r in lightning)
    assert dashboard.weather_series(now) == []
    samples = [{'t': (now - timedelta(hours=h)).isoformat(), 'temperature_c': 5 + h} for h in (30, 2, 1)]
    (tmp_path / 'weather_station_series.json').write_text(json.dumps({'samples': samples}))
    assert [p['temperature_c'] for p in dashboard.weather_series(now)] == [7.0, 6.0]



def test_dashboard_hour_falls_back_to_local_minutes(tmp_path):
    dashboard = load_source_module('dashboard_minute_source', ROOT / 'weathercam_dashboard/dashboard.py')
    dashboard.LD = tmp_path
    end = datetime.now(timezone.utc)
    samples = [{'t': (end - timedelta(minutes=m)).isoformat(), 'temperature_c': 5.0 + m, 'wind_speed_mph': 2.0} for m in (50, 40, 30, 10, 0)]
    (tmp_path / 'weather_station_minute.json').write_text(json.dumps({'samples': samples}))
    hour = dashboard.weather_hour()
    assert hour['source'] == 'local' and len(hour['temperature_c']) == 60
    assert hour['temperature_c'][59] == 5.0 and hour['temperature_c'][29] == 35.0 and hour['temperature_c'][0] is None



def test_station_analytics(tmp_path):
    dashboard = load_source_module('dashboard_analytics_source', ROOT / 'weathercam_dashboard/dashboard.py')
    dashboard.LD = tmp_path
    noon = datetime(2026, 6, 21, 11, 0, tzinfo=timezone.utc)
    cloudy = dashboard.solar_check({'solar_radiation_wm2': 100}, {'cloud_cover_pct': 5}, noon)
    assert cloudy['verdict'] == 'CAMERA_CLEARER' and cloudy['solar_cloud_pct'] > 80
    assert dashboard.solar_check({'solar_radiation_wm2': 100}, {}, datetime(2026, 12, 21, 0, 0, tzinfo=timezone.utc)) is None
    history = {'year_records': {'temp_max_c': {'value': 30.0}, 'pressure_min_hpa': {'value': 980.0}}}
    assert dashboard.record_notes({'temperature_c': 31, 'pressure_hpa': 1000}, history)[0].startswith('Year-to-date temperature high')
    assert dashboard.record_notes({'temperature_c': 20}, history) == []
    assert 'Freezing' in dashboard.frost_notes({'temperature_c': -1})[0] and 'Frost risk' in dashboard.frost_notes({'temperature_c': 2, 'dew_point_c': 0})[0]
    assert dashboard.frost_notes({'temperature_c': 10}) == []
    series = [{'t': (noon + timedelta(minutes=5 * i)).isoformat(), 'wind_direction_deg': 90, 'wind_speed_mph': 4, 'lightning_strikes_today': 0 if i < 2 else 3,
               'temperature_c': 5, 'dew_point_c': 4.5, 'humidity_percent': 97} for i in range(8)]
    rose = dashboard.wind_rose(series, {})
    assert rose['percent'][4] == 100.0
    messages = [e['message'] for e in dashboard.weather_events(series)]
    assert any(m.startswith('Lightning') for m in messages) and any(m.startswith('Fog') for m in messages)
    assert dashboard.weather_summary(series)['lightning_today'] == 3.0


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

def test_release_zip_extracts_to_matching_directory(tmp_path):
    subprocess.run(['python3', str(ROOT / 'build_release.py'), str(tmp_path)], check=True, capture_output=True)
    import zipfile
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    with zipfile.ZipFile(tmp_path / manifest['package']) as archive:
        names = archive.namelist()
    assert manifest['package'] == f'HWS-Webcam-Control-{NUM}.zip'
    assert all(name.startswith(f'HWS-Webcam-Control-{NUM}/') for name in names)
    assert f'HWS-Webcam-Control-{NUM}/manifest.json' in names
    for name in ('install.sh', 'rollback.sh', 'verify.py', 'release.py', 'update.sh', 'alerts.py'):
        assert f'HWS-Webcam-Control-{NUM}/' + name in names

def _load_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv('WEATHERCAM_ROOT', str(tmp_path))
    monkeypatch.setenv('DASHBOARD_OUT', str(tmp_path / 'out'))
    spec = importlib.util.spec_from_file_location('dash54_7', ROOT / 'weathercam_dashboard/dashboard.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_dashboard_mode_schedule_matches_real_dawn(tmp_path, monkeypatch):
    dash = _load_dashboard(tmp_path, monkeypatch)
    now = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)
    schedule = dash.mode_schedule(now, back_hours=1, forward_hours=3)
    assert [(s['from'], s['to']) for s in schedule] == [('NIGHT', 'LOW LIGHT'), ('LOW LIGHT', 'TWILIGHT'), ('TWILIGHT', 'DAY')]
    first = datetime.fromisoformat(schedule[0]['time'])
    assert abs((first - datetime(2026, 11, 20, 6, 59, tzinfo=timezone.utc)).total_seconds()) <= 300
    upcoming = dash.next_mode_change(now, schedule)
    assert upcoming['to'] == 'LOW LIGHT' and upcoming['minutes'] > 0

def test_dashboard_moon_and_disk_forecast(tmp_path, monkeypatch):
    dash = _load_dashboard(tmp_path, monkeypatch)
    moon = dash.moon_phase(datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc))
    assert moon['phase'] == 'Full moon' and moon['illumination_percent'] > 95
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    rows = [{'_ts': now - timedelta(hours=h), 'storage': {'used_percent': 50 - h / 24}} for h in range(117, -1, -3)]
    forecast = dash.disk_forecast(rows, now)
    assert forecast['percent_per_day'] > 0 and forecast['days_to_full'] > 0
    assert dash.disk_forecast(rows[:5], now) is None

def test_dashboard_template_and_event_tag():
    dashboard = (ROOT / 'weathercam_dashboard/dashboard.py').read_text(encoding='utf-8')
    template = (ROOT / 'weathercam_dashboard/templates/dashboard.html').read_text(encoding='utf-8')
    assert '[MODE TRANSITION]' in dashboard and '[MODE CHANGE]' not in dashboard
    for ident in ('sunStats', 'modeStrip', 'eventStrip', 'calendarGrid', 'libraryRows', 'keogramStack', 'gainChart', 'nightToggle'):
        assert f'id="{ident}"' in template

def _camera_namespace(tmp_path, **extra):
    ns = load_v52_namespace(tmp_path, 'modes.py', 'exposure.py', 'image_quality.py')
    morning = datetime(2026, 11, 20, 6, 0).astimezone()
    ns.update({
        'NIGHT_ELEVATION': -5.0, 'NIGHT_DAWN_CAP_START_ELEVATION': -8.0, 'MAX_NIGHT_EXPOSURE_US': 4500000,
        'MAX_LOW_LIGHT_EXPOSURE_US': 1500000, 'MAX_TWILIGHT_EXPOSURE_US': 1000000, 'current_solar_elevation': -10.0,
        'get_harpenden_sun_times': lambda: (morning.replace(hour=7), morning.replace(hour=16)),
        'local_now': lambda: morning, 'BRIGHTNESS_FILTER_ALPHA': 0.2, 'DAWN_BRIGHTNESS_FILTER_ALPHA': 0.1,
        'NIGHT_QUALITY_NOISY_GAIN': 3.2, 'NIGHT_QUALITY_WASH_BRIGHTNESS': 85.0, 'NIGHT_MAX_HIGHLIGHT_PERCENT': 5.0,
        'NIGHT_OBSERVABILITY_MIN_BRIGHTNESS': 18.0, 'night_quality_state': 'N/A', 'manual_gain': 1.5,
    })
    ns.update(extra)
    return ns

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


def test_dashboard_modules_are_included(tmp_path):
    dashboard = load_source_module('dashboard_modules_source', ROOT / 'weathercam_dashboard/dashboard.py')
    for name in ('weather_series', 'moon_phase', 'recommended_checks', 'quality_summary', 'solar_elevation'):
        assert callable(getattr(dashboard, name))


def _dash(tmp_path):
    dash = load_source_module('dash_insights', ROOT / 'weathercam_dashboard/dashboard.py')
    dash.LD = tmp_path
    dash.FORECAST_ENABLED = False
    return dash


def test_insights_events_forecast_and_statistics(tmp_path):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    scene = [{'t': now - timedelta(minutes=60 - i), 'fog_index': 5 + i * 1.0, 'humidity_percent': 92 + i * 0.1, 'temperature_c': 8 - i * 0.05,
              'alerts': [], 'mode': 'DAY', 'cloud_cover_pct': 50.0, 'rain_rate_mm_h': 0.0} for i in range(61)]
    scene.append({'t': now, 'fog_index': 60.0, 'humidity_percent': 95, 'temperature_c': 5, 'alerts': [], 'mode': 'DAY', 'cloud_cover_pct': 50.0, 'rain_rate_mm_h': 6.0})
    events = dash.smart_events(scene, [], now)
    kinds = {e['message'].split(':')[0] for e in events}
    assert 'Rapid fog formation' in kinds and 'Heavy rain onset' in kinds

    tele = [{'_ts': now - timedelta(minutes=i), 'image_quality_score': str(90 - i * 0.5), 'sharpness_score': '50', 'camera_mode': 'DAY'} for i in range(0, 60)]
    forecast = dash.quality_forecast(tele, now)
    assert forecast['next_hour']['label'] and 0 <= forecast['next_hour']['score'] <= 100
    assert dash.quality_forecast([], now) is None

    low = [{'_ts': now - timedelta(minutes=i), 'image_quality_score': '30'} for i in range(10)]
    why = dash.quality_explanation(scene, low, now)
    assert why['status'] == 'POOR' and 'humidity' in why['text']

    corr = dash.correlations(scene, tele, now)
    assert corr['items'][0]['n'] >= 30 and corr['items'][0]['r'] is not None

    stats_path = tmp_path / 'stats.json'
    days = dash.update_daily_stats(stats_path, tele, scene, [], now + timedelta(days=1))
    assert '2026-11-20' in days and stats_path.exists()
    report = dash.long_term_report(days)
    assert report['months'][0]['month'] == '2026-11' and report['year'] is None


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


def test_station_status_flags_stale_data(tmp_path):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    assert dash.station_status(now)['known'] is False
    (tmp_path / 'weather_station.json').write_text(json.dumps({'updated': (now - timedelta(minutes=30)).isoformat()}))
    assert dash.station_status(now)['stale'] is True
    (tmp_path / 'weather_station.json').write_text(json.dumps({'updated': now.isoformat(), 'bridge_data_age_s': 700}))
    assert dash.station_status(now)['stale'] is True
    (tmp_path / 'weather_station.json').write_text(json.dumps({'updated': now.isoformat(), 'bridge_data_age_s': 5}))
    assert dash.station_status(now)['stale'] is False


def test_console_page_is_generated(tmp_path, monkeypatch):
    dash = _dash(tmp_path)
    monkeypatch.setattr(dash, 'OUT', tmp_path / 'out')
    dash.generate(False)
    page = (tmp_path / 'out' / 'console.html').read_text()
    assert 'Wind compass' in page and '__DATA__' not in page and 'HWS.refreshWeather' in page


def test_graph_data_buckets_and_pages(tmp_path, monkeypatch):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    series = [{'t': (now - timedelta(minutes=i)).isoformat(), 'temperature_c': 10.0 + (i % 2), 'wind_gust_mph': i, 'rain_today_mm': 1.0} for i in range(120)]
    scene = [{'t': now - timedelta(hours=i), 'temperature_c': 5.0, 'rain_rate_mm_h': None} for i in range(48)]
    graphs = dash.graph_data(now, series, scene, {'2026-11-19': {'temp_max_c': 9.0}}, {'daily': [{'date': '2026-11-18', 'temp_max_c': 8.0, 'temp_min_c': 1.0}]})
    day = graphs['24h']
    assert len(day['t']) == len(day['temperature_c']) <= 25 and 10.0 <= day['temperature_c'][0] <= 11.0
    assert max(day['wind_gust_mph']) == 119 or max(day['wind_gust_mph']) >= 115
    assert len(graphs['7d']['t']) >= 47 and graphs['7d']['temperature_c'][0] == 5.0
    assert [d['date'] for d in graphs['daily']] == ['2026-11-18', '2026-11-19']
    monkeypatch.setattr(dash, 'OUT', tmp_path / 'out')
    dash.generate(False)
    page = (tmp_path / 'out' / 'graphs.html').read_text()
    assert '__DATA__' not in page and 'graph-data' in page


def test_forecast_parse_cache_and_site_pages(tmp_path, monkeypatch):
    import io, json as _json, urllib.request
    dash = _dash(tmp_path)
    series = [{'time': f'2026-11-22T{h:02d}:00:00Z', 'data': {'instant': {'details': {'air_temperature': 5.0 + h / 4, 'wind_speed': 4.0, 'wind_from_direction': 225, 'relative_humidity': 80, 'cloud_area_fraction': 50, 'air_pressure_at_sea_level': 1010}},
              'next_1_hours': {'summary': {'symbol_code': 'rain'}, 'details': {'precipitation_amount': 0.5}}}} for h in range(24)]
    doc = {'properties': {'timeseries': series}}
    calls = []

    class Reply(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, 'urlopen', lambda req, timeout=0: calls.append(req) or Reply(_json.dumps(doc).encode()))
    dash.FORECAST_ENABLED = True
    now = datetime(2026, 11, 22, 8, 0, tzinfo=timezone.utc)
    result = dash.forecast_data(now)
    assert len(result['hourly']) == 24 and result['hourly'][0]['wind_mph'] == 8.9 and result['daily'][0]['rain_mm'] == 12.0
    assert 'HWS-Webcam-Control' in calls[0].get_header('User-agent')
    dash.forecast_data(now + timedelta(minutes=10))
    assert len(calls) == 1
    monkeypatch.setattr(urllib.request, 'urlopen', lambda req, timeout=0: (_ for _ in ()).throw(OSError('offline')))
    assert dash.forecast_data(now + timedelta(hours=3))['stale'] is True
    assert dash.forecast_data(now + timedelta(hours=20)) is None
    dash.FORECAST_ENABLED = False
    monkeypatch.setattr(dash, 'OUT', tmp_path / 'out')
    dash.generate(False)
    for name in ('forecast.html', 'about.html', 'station.html', 'mobile.html', 'graphs.html', 'console.html', 'dashboard.html'):
        page = (tmp_path / 'out' / name).read_text()
        assert '__DATA__' not in page and '__NAV__' not in page and 'forecast.html' in page


def test_daily_rainfall_total_reaches_graph_data(tmp_path):
    dash = _dash(tmp_path)
    day = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc).date()
    scene = [{'t': datetime(2026, 11, 19, h, 0, tzinfo=timezone.utc), 'rain_today_mm': h / 4} for h in range(24)]
    assert dash._day_stats(day, [], scene, None)['rain_mm'] == 5.75
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    graphs = dash.graph_data(now, [], [], {'2026-11-19': {'rain_mm': 5.75}}, {'daily': [{'date': '2026-11-18', 'rain_mm': 2.0}]})
    assert [d['rain_mm'] for d in graphs['daily']] == [2.0, 5.75]

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


def test_meteobridge_daily_history_reaches_year_graph(tmp_path):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
    graphs = dash.graph_data(now, [], [], {}, local_daily={
        '2025-12-01': {'rain_mm': 4.0, 'cpu_load_avg': 21.3, 'current_avg': 0.42},
        '2026-11-23': {'rain_mm': 0.0, 'cpu_load_avg': 15.0},
    })
    assert graphs['daily'][0]['cpu_load_avg'] == 21.3
    assert graphs['daily'][0]['current_avg'] == 0.42
    assert graphs['daily'][1]['rain_mm'] == 0.0


def test_meteobridge_health_history_year_selection_and_monthly_aggregation():
    import shutil
    if not shutil.which('node'):
        pytest.skip('Node is required for the Meteobridge history regression')
    template = (ROOT / 'weathercam_dashboard/templates/mbhealth.html').read_text(encoding='utf-8')
    script = template[template.index('const historyMap='):template.index('</script></div>')]
    harness = r"""
const assert=require('assert');
const D={graphs:{daily:[
 {date:'2024-01-02',cpu_load_avg:0,uptime_last:10,signal_min:5,signal_max:20},
 {date:'2024-01-31',cpu_load_avg:20,uptime_last:30,signal_min:3,signal_max:25},
 {date:'2024-03-01',cpu_load_avg:30,uptime_last:40},
 {date:'2025-08-01',rain_mm:4},
 {date:'2026-11-23',cpu_load_avg:50,uptime_last:100}
]}};
const has=v=>v!==null&&v!==undefined&&v!==''&&isFinite(Number(v));
const specs=[['CPU load','cpu_load_percent','%','#f00'],['Uptime','bridge_uptime_hours','h','#00f']];
const year={children:[],value:'',hidden:true},note={textContent:''},chart={children:[],set textContent(v){this.children=[]}};
const tabs={children:[],querySelectorAll(){return this.children}};
let drawn=[];
const HWS={chart(box,o){drawn.push(o)}};
function el(tag,cls,text,parent){
 const e={tag,textContent:text,children:[],classList:{add(){},remove(){}}};
 if(parent){parent.children.push(e);if(parent===year&&!year.value)year.value=text;}
 return e;
}
""" + script + r"""
assert.deepStrictEqual(year.children.map(o=>o.value),['2026','2024']);
year.value='2024';drawn=[];renderPeriod('daily');
assert.equal(drawn[0].series[0].pts.length,3);
assert.deepStrictEqual(drawn[0].series[0].pts.map(p=>p[1]),[0,20,30]);
assert(note.textContent.includes('3 recorded days'));
drawn=[];renderPeriod('monthly');
assert.deepStrictEqual(drawn[0].series[0].pts.map(p=>p[1]),[10,30]);
assert.deepStrictEqual(drawn[1].series[0].pts.map(p=>p[1]),[30,40]);
assert.deepStrictEqual(drawn[2].series.map(s=>s.pts.map(p=>p[1])),[[3],[25]]);
year.value='2026';drawn=[];year.onchange();
assert.deepStrictEqual(drawn[0].series[0].pts.map(p=>p[1]),[50]);
renderPeriod('24h');assert(year.hidden);
"""
    subprocess.run(['node', '-e', harness], check=True, capture_output=True, text=True)


def test_board_temperatures_reach_all_graph_periods(tmp_path):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 23, 12, 4, tzinfo=timezone.utc)
    (tmp_path / 'weather_station_series.json').write_text(json.dumps({'samples': [
        {'t': now.isoformat(), 'base_board_temperature_c': 35.5, 'rf_board_temperature_c': 40.2},
    ]}))
    scene_path = tmp_path / 'scene'
    scene_path.mkdir()
    (scene_path / 'scene_20261123.jsonl').write_text(json.dumps({
        'timestamp': now.isoformat(), 'base_board_temperature_c': 34, 'rf_board_temperature_c': 39,
    }) + '\n')
    graphs = dash.graph_data(now, dash.weather_series(now), dash.scene_records(now), {}, archive={
        '2025-11-23': {'base_board_temp_avg_c': 30, 'rf_board_temp_avg_c': 32, 'soil_wetness_avg_cbar': 80},
    })
    assert graphs['24h']['base_board_temperature_c'] == [35.5]
    for period in ('7d', 'month'):
        assert graphs[period]['base_board_temperature_c'] == [34]
        assert graphs[period]['rf_board_temperature_c'] == [39]
    assert graphs['daily'][0]['base_board_temp_avg_c'] == 30
    assert graphs['daily'][0]['rf_board_temp_avg_c'] == 32
    assert graphs['daily'][0]['soil_wetness_avg_cbar'] == 80


def test_signal_graph_extrema_and_legacy_units(tmp_path):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 23, 12, 4, tzinfo=timezone.utc)
    rows = [
        {'t': now - timedelta(minutes=3), 'signal_min': 22, 'signal_max': 55},
        {'t': now - timedelta(minutes=2), 'signal_min': 11, 'signal_max': 80},
    ]
    graphs = dash.graph_data(now, rows, rows, {}, local_daily={
        '2026-11-22': {'signal_min': 3, 'signal_max': 94, 'uptime_last': 72},
    })
    for period in ('24h', '7d', 'month'):
        assert graphs[period]['signal_min'] == [11]
        assert graphs[period]['signal_max'] == [80]
    assert graphs['daily'][0]['signal_min'] == 3
    assert graphs['daily'][0]['signal_max'] == 94
    assert graphs['daily'][0]['uptime_last'] == 72
    (tmp_path / 'weather_station_series.json').write_text(json.dumps({'samples': [
        {'t': now.isoformat(), 'soil_moisture_percent': 85, 'uptime_seconds': 48},
    ]}))
    old = dash.weather_series(now)[0]
    assert old['soil_wetness_cbar'] == 85 and old['bridge_uptime_hours'] == 48
    assert dash.normalise_station_units({'soil_moisture_percent': 0, 'uptime_seconds': 48})['soil_wetness_cbar'] == 0

def test_publication_removes_only_retired_data_page(tmp_path):
    dash = _dash(tmp_path)
    dash.OUT = tmp_path
    (tmp_path / 'weather-live.json').write_text('{"updated":"old"}')
    class FTP:
        directory = '/'
        deleted = []
        def connect(self, *args, **kwargs): pass
        def login(self, *args): pass
        def cwd(self, directory): self.directory = directory
        def mkd(self, directory): pass
        def nlst(self): return ['data.html', 'unrelated.html'] if self.directory == '/' else []
        def delete(self, name): self.deleted.append(name)
        def quit(self): pass
    ftp = FTP()
    assert dash.publish_with(ftp, 'host', 'user', 'password', '/', set())['remote_verified']
    assert ftp.deleted == ['data.html']


def test_calendar_month_filters_include_31st_and_exclude_previous_month(tmp_path):
    dash = _dash(tmp_path)
    now = datetime(2026, 7, 31, 12, tzinfo=timezone.utc)
    start = dash.month_start(now)
    assert start == datetime(2026, 6, 30, 23, tzinfo=timezone.utc)
    scene = [{'t': start + timedelta(minutes=i), 'temperature_c': 7.0,
              'wind_direction_deg': 90, 'wind_speed_mph': 8.0} for i in range(6)]
    scene.insert(0, {'t': start - timedelta(seconds=1), 'temperature_c': 99.0,
                     'wind_direction_deg': 180, 'wind_speed_mph': 25.0})
    graph = dash.graph_data(now, [], scene, {})['month']
    assert graph['temperature_c'] == [7.0]
    rose = dash.wind_rose_periods(now, [], scene)['month']
    assert rose['samples'] == 6
    assert rose['percent'][4][1] == 100
    feb = datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert dash.graph_data(feb, [], scene, {})['month']['t'] == []
    october = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)
    start = dash.month_start(october)
    assert october - start > timedelta(days=31)
    first = [{'t': start, 'temperature_c': 6.0}]
    assert dash.graph_data(october, [], first, {})['month']['temperature_c'] == [6.0]


def test_news_command_persists_and_renders_and_rejects_bad_input(tmp_path, monkeypatch):
    import pytest
    dash = _dash(tmp_path)
    monkeypatch.setattr(dash, 'OUT', tmp_path / 'out')
    dash.add_news('Station Update', 'Serviced.\nNew sensors.', '2026-11-23')
    stored = json.loads((tmp_path / 'dashboard_news.json').read_text())
    assert stored[0]['text'] == 'Serviced.\nNew sensors.'
    dash.generate(False)
    assert 'Station Update' in (dash.OUT / 'news.html').read_text()
    assert 'Station Update' in (dash.OUT / 'indexnew.html').read_text()
    with pytest.raises(ValueError, match='already exists'):
        dash.add_news('Station Update', 'Duplicate', '2026-11-23')
    with pytest.raises(ValueError):
        dash.add_news('Invalid Date', 'Text', '2026-02-30')
    assert len(dash.local_news()) == 1
    (tmp_path / 'dashboard_news.json').write_text('{broken')
    with pytest.raises(ValueError):
        dash.add_news('New Entry', 'Do not overwrite corrupt history')


def test_browser_weather_refresh_fallback_and_monotonic_dates():
    import shutil
    import pytest
    if not shutil.which('node'):
        pytest.skip('Node is required for the browser helper regression')
    script = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context={console,Date,Intl,Number,Error,localStorage:{getItem(){return null}},
 document:{documentElement:{dataset:{}},addEventListener(){}},window:{},fetch:null};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const H=context.window.HWS;
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


def test_site_pages_assets_records_and_almanac(tmp_path, monkeypatch):
    dash = _dash(tmp_path)
    monkeypatch.setattr(dash, 'OUT', tmp_path / 'out')
    dash.generate(False)
    out = tmp_path / 'out'
    for name in ('index.html', 'indexnew.html', 'webcam.html', 'radar.html', 'satellite.html', 'records.html', 'reports.html', 'almanac.html', 'health.html', 'webcamhealth.html', 'rainfall.html', 'donate.html', 'compare.html', 'wind.html', 'news.html', 'mbhealth.html', 'pihealth.html'):
        page = (out / name).read_text()
        assert '__DATA__' not in page and '__NAV__' not in page and 'site.js' in page and ('reports.html' in page or name == 'index.html')
    chooser = (out / 'index.html').read_text()
    assert 'indexold.php' in chooser and 'indexnew.html' in chooser and 'mailto:info@harpendenweatherstation.co.uk' in chooser
    assert '&copy; 2026 Mark Sanders' in chooser
    assert 'site.js' in (out / 'dashboard.html').read_text()
    assert (out / 'site.css').is_file() and (out / 'favicon.png').is_file() and (out / 'logo.png').is_file()
    assert not (out / 'redirects.htaccess').exists()
    monkeypatch.setenv('DASHBOARD_WRITE_REDIRECTS', '1')
    dash.generate(False)
    assert 'RewriteRule ^about\\.php$ about.html [R=301,L]' in (out / 'redirects.htaccess').read_text()
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    daily = [{'date': '2026-11-20', 'temp_max_c': 9.0, 'temp_min_c': 2.0, 'rain_mm': 0.0}, {'date': '2026-11-21', 'temp_max_c': 11.5, 'temp_min_c': -1.0, 'rain_mm': 7.4, 'wind_gust_mph': 31},
             {'date': '2025-07-01', 'temp_max_c': 33.0, 'temp_min_c': 15.0, 'rain_mm': 0.1}]
    rec = dash.records_data(daily, now)
    assert rec['month']['hottest_c'] == {'value': 11.5, 'date': '2026-11-21'} and rec['month']['rain_total_mm'] == 7.4 and rec['month']['rain_days'] == 1
    assert rec['all']['hottest_c']['value'] == 33.0 and rec['year']['days'] == 2 and rec['all']['coldest_c']['value'] == -1.0
    alm = dash.almanac_data(now, 3)
    assert len(alm) == 3 and alm[0]['sunrise'] < alm[0]['sunset'] and alm[0]['dark_start'] and alm[0]['moon']


def test_backfill_from_meteobridge_and_archive_merge(tmp_path):
    import weather_station as ws
    assert ws.parse_backfill_day('temp_max_c=11.2;temp_min_c=--;rain_mm=3.5;wind_gust_mph=999;humidity_avg=80') == {'temp_max_c': 11.2, 'rain_mm': 3.5, 'humidity_avg': 80.0}
    assert 'th0temp-max@D7' in dict(ws.backfill_expressions(7))['temp_max_c'] and dict(ws.backfill_expressions(7))['wind_gust_mph'] == 'wind0wind-max@D7=mph'
    today = datetime(2026, 11, 22).date()
    replies = {}

    def fetch(url):
        from urllib.parse import unquote
        offset = int(unquote(url).split('th0temp-max@D')[1].split(']')[0])
        return f'temp_max_c={10 + offset};temp_min_c=1;rain_mm=0.5;rain_max_mm_h=2.4' if offset <= 3 else 'temp_max_c=--;temp_min_c=--'
    path = tmp_path / 'archive.json'
    result = ws.backfill_archive('192.168.0.65', str(path), days=100, today=today, fetch=fetch, sleep=lambda s: None, max_empty=5)
    assert result == {'added': 3, 'total': 3, 'first': '2026-11-19'}
    assert ws.backfill_archive('192.168.0.65', str(path), days=100, today=today, fetch=fetch, sleep=lambda s: None, max_empty=5)['added'] == 0
    dash = _dash(tmp_path)
    (tmp_path / 'weather_station_archive.json').write_text(path.read_text())
    archive = dash.weather_archive()
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    graphs = dash.graph_data(now, [], [], {'2026-11-21': {'temp_max_c': 5.0}}, None, archive)
    by_day = {d['date']: d for d in graphs['daily']}
    assert by_day['2026-11-21']['temp_max_c'] == 5.0 and by_day['2026-11-20']['temp_max_c'] == 12.0 and by_day['2026-11-20']['rain_mm'] == 0.5


def test_v54_news_today_wind_and_meteobridge_health(tmp_path):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    news = dash.news_items({'news': [{'date': '2030-11-01', 'title': 'Mine', 'text': 'x'}]})
    assert news[0]['title'] == 'Mine' and len(news) > 40 and news == sorted(news, key=lambda n: (n['date'], n['time']), reverse=True)
    daily = [{'date': '2025-11-22', 'temp_max_c': 10.0, 'temp_min_c': 3.0, 'rain_mm': 4.0}, {'date': '2024-11-22', 'temp_max_c': 12.0, 'temp_min_c': -2.0, 'rain_mm': 0.0}]
    today = dash.today_in_harpenden(now, daily)
    assert today['hottest'] == {'value': 12.0, 'year': '2024'} and today['coldest']['value'] == -2.0 and today['wettest']['year'] == '2025' and today['day_length_change_seconds'] < 0
    points = [{'wind_direction_deg': 270, 'wind_speed_mph': 12}] * 8 + [{'wind_direction_deg': 0, 'wind_speed_mph': 0.1}] * 2
    rose = dash.wind_rose_periods(now, points, [])
    assert list(rose) == ['24h'] and rose['24h']['calm_percent'] == 20.0 and rose['24h']['percent'][12][2] == 80.0
    health = dash.meteobridge_health(now, {'updated': now.isoformat(), 'bridge_data_age_s': 20}, {}, [{'date': '2026-11-21', 'rain_mm': 1.0}], {'2026-11-21': {}})
    status = {c['name']: c['status'] for c in health['checks']}
    assert status['Latest reading'] == 'ok' and status['Daily history (30 days)'] == 'bad'


def test_sun_highlight_frame_selection():
    source = (ROOT / 'timelapse.py').read_text(encoding='utf-8')
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'select_highlight_frames')
    namespace = {'datetime': datetime, 'timedelta': __import__('datetime').timedelta, 'os': os}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<hl>', 'exec'), namespace)
    frames = [f'/f/frame_20261122_{h:02d}{m:02d}00.jpg' for h in range(6, 10) for m in range(0, 60)]
    chosen = namespace['select_highlight_frames'](frames, datetime(2026, 11, 22, 8, 0), 30)
    assert chosen[0].endswith('073000.jpg') and chosen[-1].endswith('083000.jpg') and len(chosen) == 61
    assert len(namespace['select_highlight_frames'](frames, datetime(2026, 11, 22, 8, 0), 120, limit=50)) == 50


def test_alerts_and_share_card(tmp_path, monkeypatch):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    alerts = dash.weather_alerts({'temperature_c': -1.0, 'wind_gust_mph': 45, 'rain_rate_mm_h': 2})
    assert [a['key'] for a in alerts] == ['frost', 'gust'] and dash.weather_alerts({'temperature_c': 5}) == []
    state = tmp_path / 'alerts.json'
    assert dash.send_alerts(alerts, now, state) == []
    sent = []
    monkeypatch.setenv('DASHBOARD_ALERT_NTFY_URL', 'http://example.invalid/topic')
    import urllib.request
    class _R:
        def close(self): pass
    monkeypatch.setattr(urllib.request, 'urlopen', lambda req, timeout=0: sent.append(req.data) or _R())
    assert dash.send_alerts(alerts, now, state) == ['frost', 'gust'] and len(sent) == 1
    assert dash.send_alerts(alerts, now + __import__('datetime').timedelta(hours=1), state) == [] and len(sent) == 1
    assert dash.send_alerts(alerts, now + __import__('datetime').timedelta(hours=7), state) == ['frost', 'gust']
    out = tmp_path / 'share.png'
    assert dash.share_card({'temperature_c': 7.5, 'wind_direction_deg': 131}, now, out) and out.read_bytes()[:4] == b'\x89PNG'


def test_meteobridge_sunshine_minutes_become_hours():
    import datetime as dt
    import weather_station as ws
    v = ws.parse_meteobridge('temperature_c=5;sunshine_hours_today=354', dt.datetime.now(dt.timezone.utc))
    assert abs(v['sunshine_hours_today'] - 5.9) < 0.01


def test_meteobridge_headers_fall_back_to_environment(monkeypatch):
    import weather_station as ws
    monkeypatch.setattr(ws, 'METEOBRIDGE_PASSWORD', '')
    monkeypatch.setenv('HWS_METEOBRIDGE_PASSWORD', 'pw')
    monkeypatch.setenv('HWS_METEOBRIDGE_USER', 'bob')
    assert ws._meteobridge_headers()['Authorization'].startswith('Basic ')


def test_meteobridge_health_flags_blank_live_fields():
    import datetime as dt
    from weathercam_dashboard import dashboard as d
    now = dt.datetime.now(dt.timezone.utc)
    w = {'source': 'meteobridge', 'updated': now.isoformat(), 'temperature_c': 5}
    h = d.meteobridge_health(now, w, {}, [], {})
    live = [c for c in h['checks'] if c['name'] == 'Live fields'][0]
    assert live['status'] == 'warn' and 'rain today' in live['detail']


def test_clientraw_support_is_gone():
    assert 'clientraw' not in (ROOT / 'weather_station.py').read_text(encoding='utf-8').lower()
    assert 'clientraw' not in (ROOT / 'weathercam_dashboard/templates/dashboard.html').read_text(encoding='utf-8').lower()


def test_dashboard_uses_full_weather_reading(tmp_path, monkeypatch):
    dashboard = load_source_module('dashboard_full_weather_source', ROOT / 'weathercam_dashboard/dashboard.py')
    dashboard.LD = tmp_path
    now = datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)
    trimmed = {'temperature_c': 1.0, 'age_seconds': 5}
    assert dashboard.weather_full(now, trimmed) == trimmed
    fresh = {'updated': (now - timedelta(seconds=30)).isoformat(), 'source': 'meteobridge', 'rain_today_mm': 2.0, 'bridge_data_age_s': 3}
    (tmp_path / 'weather_station.json').write_text(json.dumps(fresh))
    full = dashboard.weather_full(now, trimmed)
    assert full['rain_today_mm'] == 2.0 and full['source'] == 'meteobridge' and full['age_seconds'] == 30
    fresh['updated'] = (now - timedelta(hours=2)).isoformat()
    (tmp_path / 'weather_station.json').write_text(json.dumps(fresh))
    stale = dashboard.weather_full(now, trimmed)
    assert stale['updated'] == fresh['updated'] and stale['age_seconds'] == 7200
    newer = {'updated': (now - timedelta(hours=1)).isoformat(), 'temperature_c': 3}
    assert dashboard.weather_full(now, newer) == newer
    custom = tmp_path / 'custom.json'
    custom.write_text(json.dumps({'updated': now.isoformat(), 'temperature_c': 12}))
    monkeypatch.setenv('HWS_WEATHER_DATA_PATH', str(custom))
    assert dashboard.weather_full(now)['temperature_c'] == 12
    assert dashboard.station_status(now)['known'] is True


def test_record_daily_tracks_rain_rate_pressure_and_gust(tmp_path):
    import weather_station as ws
    path = str(tmp_path / 'd.json')
    for rate, pressure, gust in ((0.0, 1000.0, 5.0), (4.2, 1004.0, 12.0), (1.0, 998.0, 12.0)):
        ws.record_daily({'updated': '2026-11-23T07:00:00+00:00', 'temperature_c': 1.0, 'pressure_hpa': pressure,
                         'rain_rate_mm_h': rate, 'wind_gust_max_today_mph': gust}, path)
    day = json.loads(open(path).read())['days']['2026-11-23']
    assert day['rain_max_mm_h'] == 4.2 and day['pressure_max_hpa'] == 1004.0 and day['pressure_min_hpa'] == 998.0 and day['wind_gust_mph'] == 12.0



def test_wind_sensor_health_check(tmp_path):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc)
    live = {'updated': now.isoformat(), 'source': 'meteobridge', 'bridge_data_age_s': 3, 'temperature_c': 1.0}
    assert {c['name']: c['status'] for c in dash.meteobridge_health(now, live, {}, [], {})['checks']}['Wind sensor'] == 'warn'
    live.update(wind_speed_mph=2.0)
    assert {c['name']: c['status'] for c in dash.meteobridge_health(now, live, {}, [], {})['checks']}['Wind sensor'] == 'ok'


def test_backfill_parses_extra_daily_fields():
    import weather_station as ws
    out = ws.parse_backfill_day('wind_avg_mph=4.2;dew_min_c=-2.5;solar_max_wm2=310;uv_max=1.2;sunshine_min=354;humidity_max=99;heat_index_max_c=[bad]')
    assert out == {'wind_avg_mph': 4.2, 'dew_min_c': -2.5, 'solar_max_wm2': 310.0, 'uv_max': 1.2, 'sunshine_hours': 5.9, 'humidity_max': 99.0}
    assert ws.parse_backfill_day('sunshine_min=50000') == {}


def test_alerts_report_once_repeat_and_recover():
    spec = importlib.util.spec_from_file_location('hws_alerts', ROOT / 'alerts.py')
    alerts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(alerts)
    messages, state = alerts.decide({'capture': 'old image'}, {}, 1000, 3600)
    assert messages == ['PROBLEM: old image']
    assert alerts.decide({'capture': 'old image'}, state, 1100, 3600)[0] == []
    assert alerts.decide({'capture': 'old image'}, state, 5000, 3600)[0] == ['STILL: old image']
    messages, state = alerts.decide({}, state, 5100, 3600)
    assert messages == ['RECOVERED: old image'] and state == {}
