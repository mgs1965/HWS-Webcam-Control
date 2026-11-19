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
    assert namespace['VERSION'] == 'V51.0'
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

def test_dashboard_v51_0_payload():
    dashboard = (ROOT / 'weathercam_dashboard/dashboard.py').read_text(encoding='utf-8')
    template = (ROOT / 'weathercam_dashboard/templates/dashboard.html').read_text(encoding='utf-8')
    assert "V='51.0'" in dashboard
    assert "'release':'V51.0'" in dashboard
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
    installer = (ROOT / 'install_v51_0.sh').read_text(encoding='utf-8')
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
