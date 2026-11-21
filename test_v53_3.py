#!/usr/bin/env python3
from pathlib import Path
import ast
import importlib.util
import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent

def test_release_identity():
    namespace = {}
    exec((ROOT / 'version.py').read_text(encoding='utf-8'), namespace)
    assert namespace['VERSION'] == 'V53.3'
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

def test_dashboard_v53_3_payload():
    dashboard = (ROOT / 'weathercam_dashboard/dashboard.py').read_text(encoding='utf-8')
    template = (ROOT / 'weathercam_dashboard/templates/dashboard.html').read_text(encoding='utf-8')
    assert "V='53.3'" in dashboard
    assert "'release':'V53.3'" in dashboard
    assert "for period,hours in (('24h',24),('7d',168),('30d',720))" in dashboard
    assert 'incidents' in dashboard
    assert "'process_memory':('health','memory.process_rss_bytes',1/1048576)" in dashboard
    assert 'V49.11.2' not in template
    assert 'data-view="gallery"' not in template
    for view in ('live', 'trends', 'events', 'advanced', 'reports', 'archive'):
        assert f'id="{view}"' in template
    assert 'Diagnostics</button>' not in template
    assert 'data-view="controller"' not in template
    for period in ('24h', '7d', '30d'):
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
        assert f'for="view-{view}"' in template
    assert '#view-live:checked~.page #live' in template
    assert '#view-trends:checked~.page #trends' in template
    assert '#view-reports:checked~.page #reports' in template
    assert '#view-archive:checked~.page #archive' in template
    assert template.index('id="view-live"') < template.index('<div class="page">')
    assert "document.querySelectorAll('.view-select')" in template
    assert 'Last 24 hours' in template
    assert 'Last 7 days' in template
    assert 'Last 30 days' in template
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
    installer = (ROOT / 'install_v53_3.sh').read_text(encoding='utf-8')
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


def test_dashboard_weather_raw_rows(tmp_path):
    dashboard = load_source_module('dashboard_weather_raw_source', ROOT / 'weathercam_dashboard/dashboard.py')
    dashboard.LD = tmp_path
    assert dashboard.weather_raw() == {}
    (tmp_path / 'weather_station_raw.json').write_text(json.dumps({'clientraw': {'fetched': 't', 'tokens': ['2.7', '3.1']}, 'bad': {'tokens': 5}}))
    raw = dashboard.weather_raw()
    assert list(raw) == ['clientraw'] and raw['clientraw']['rows'][0][0] == 1
    assert raw['clientraw']['rows'][0][1].startswith('Average Windspeed') and raw['clientraw']['rows'][1][3] == '3.1'


def test_raw_files_are_recorded(tmp_path):
    import weather_station as ws
    ws.RAW_FILES.clear()
    ws.RAW_PATH = str(tmp_path / 'raw.json')
    try:
        ws.record_raw('clientraw', '12345 1 2 3')
        ws.record_raw('clientrawhour', 'garbage 1')
        ws.flush_raw()
        saved = json.loads((tmp_path / 'raw.json').read_text())
        assert list(saved) == ['clientraw'] and saved['clientraw']['tokens'] == ['1', '2', '3']
    finally:
        ws.RAW_PATH = None
        ws.RAW_FILES.clear()
    template = (ROOT / 'weathercam_dashboard/templates/dashboard.html').read_text(encoding='utf-8')
    assert 'id="view-station"' in template and 'data-raw="clientrawextra"' in template


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
    tokens = ['1'] * 481
    tokens[420] = '250'
    (tmp_path / 'weather_station_raw.json').write_text(json.dumps({'clientrawhour': {'fetched': 't', 'tokens': tokens}}))
    hour = dashboard.weather_hour()
    assert hour['solar_wm2'][0] == 250.0 and abs(hour['wind_mph'][0] - 1.15078) < 1e-6


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
    assert manifest['package'] == 'HWS-Webcam-Control-53.3.zip'
    assert all(name.startswith('HWS-Webcam-Control-53.3/') for name in names)
    assert 'HWS-Webcam-Control-53.3/manifest.json' in names

def _load_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv('WEATHERCAM_ROOT', str(tmp_path))
    monkeypatch.setenv('DASHBOARD_OUT', str(tmp_path / 'out'))
    spec = importlib.util.spec_from_file_location('dash53_3', ROOT / 'weathercam_dashboard/dashboard.py')
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

def test_dashboard_v53_3_template_and_event_tag():
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
