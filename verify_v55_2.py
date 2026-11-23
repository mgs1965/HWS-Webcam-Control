#!/usr/bin/env python3
import ast
import json
from pathlib import Path

root = Path(__file__).resolve().parent
modules = [
    'version.py', 'core.py', 'camera.py', 'modes.py', 'exposure.py',
    'v47_control.py', 'image_quality.py', 'scene_analysis.py', 'state.py', 'controller_analytics.py',
    'publishing.py', 'timelapse.py', 'keogram.py', 'monitoring.py', 'runtime.py', 'loader.py',
    'weather_camera.py', 'weathercam_dashboard/dashboard.py',
]
for filename in modules:
    compile((root / filename).read_text(encoding='utf-8'), str(root / filename), 'exec')

version = {}
exec((root / 'version.py').read_text(encoding='utf-8'), version)
assert version['VERSION'] == 'V55.2'
assert version['TELEMETRY_SCHEMA_VERSION'] == 4

manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
assert manifest['release'] == 'V55.2'
assert manifest['baseline'] == 'V51.0.2'
assert manifest['package'] == 'HWS-Webcam-Control-55.2.zip'
assert manifest['package'] == f"HWS-Webcam-Control-{version['VERSION'][1:]}.zip"
assert manifest['package_directory'] == manifest['package'][:-4]
assert all((root / filename).exists() for filename in manifest['files'])

publishing = (root / 'publishing.py').read_text(encoding='utf-8')
tree = ast.parse(publishing)
assignment = next(
    node for node in tree.body
    if isinstance(node, ast.Assign)
    and any(getattr(target, 'id', '') == 'TELEMETRY_FIELDS' for target in node.targets)
)
assert len(ast.literal_eval(assignment.value)) == 58

core = (root / 'core.py').read_text(encoding='utf-8')
assert "SCRIPT_VERSION = '2026-11-23 V55.2'" in core
assert "V51_RELEASE = 'V55.2'" in core
assert "FTP_PASSWORD = os.getenv('HWS_FTP_PASSWORD', '')" in core

dashboard = (root / 'weathercam_dashboard/dashboard.py').read_text(encoding='utf-8')
template = (root / 'weathercam_dashboard/templates/dashboard.html').read_text(encoding='utf-8')
assert "V='55.2'" in dashboard
assert "'release':'V55.2'" in dashboard
assert "('month',None)" in dashboard
assert 'older_index%5==0' in dashboard
assert "'timeline_events':timeline_events" in dashboard
assert "'coverage':chart_coverage" in dashboard
assert "'timelapse':timelapse," in dashboard
assert 'def recommended_checks' in (root / 'weathercam_dashboard/recommendations.py').read_text(encoding='utf-8')
assert template.count('__DATA__') == 1
assert "dataText.startsWith('{')?JSON.parse(dataText):{}" in template
assert "D.series?.[period]?.[key]" in template
assert "template.replace('__DATA__'" in dashboard
assert "template.count('__DATA__') != 1:raise RuntimeError" in dashboard
assert "DASHBOARD_FTP_PASSWORD" not in template
for view in ('live', 'trends', 'events', 'advanced', 'reports', 'archive'):
    assert f'id="view-{view}"' in template
    assert f'id="{view}"' in template
assert '__HEALTH_NAV__' in template and 'HEALTH_VIEWS=' in dashboard
for chart in (
    'brightnessChart', 'qualityChart', 'exposureChart', 'processMemoryChart',
    'cpuTemperatureChart', 'cpuLoadChart', 'systemMemoryChart', 'diskUsedChart',
    'throttlingChart', 'captureCompletenessChart',
):
    assert f'id="{chart}"' in template
for feature in (
    'Export this period as CSV', 'Export daily reports as CSV',
    'Recommended checks', 'Timelapse &amp; capture report',
    'Recent captures',
):
    assert feature in template

monitoring = (root / 'monitoring.py').read_text(encoding='utf-8')
assert "'throttled_now': bool(value & 0x4)" in monitoring
assert "'soft_temperature_limit_now': bool(value & 0x8)" in monitoring
assert "f'daily_health_{day:%Y%m%d}.json'" in monitoring
state = (root / 'state.py').read_text(encoding='utf-8')
assert 'quality state histories must be lists by mode' in state
camera = (root / 'camera.py').read_text(encoding='utf-8')
assert "audit_event('camera_restart_failed'" in camera
analytics = (root / 'controller_analytics.py').read_text(encoding='utf-8')
assert "'MAX_TWILIGHT_EXPOSURE_US','MAX_LOW_LIGHT_EXPOSURE_US','MAX_NIGHT_EXPOSURE_US'" in analytics
service = (root / 'systemd/weathercam.service').read_text(encoding='utf-8')
assert 'ExecStart=/usr/bin/python3 /mnt/weathercam/app/current/weather_camera.py' in service

station_service = (root / 'systemd/weathercam-weather-station.service').read_text(encoding='utf-8')
assert 'weather_station.py --interval 30' in station_service and 'Restart=on-failure' in station_service
assert (root / 'weather_station.py').is_file()
installer = (root / 'install_v55_2.sh').read_text(encoding='utf-8')
rollback = (root / 'rollback_v55_2.sh').read_text(encoding='utf-8')
assert 'HarpendenWeatherCamera-V55.2' in installer
assert 'verify_v55_2.py' in installer
assert 'weathercam-weather-station.service' in installer
assert 'systemctl cat weathercam.service' in installer
assert 'refusing to overwrite it' in installer
assert 'v55_2-rollback-target' in rollback

print('PASS: V55.2 release identity, manifest and telemetry-v4 contract')
for feature in ('eventFilters', 'staleBanner', 'overlayLegend', 'qualitySummaryRows', 'timelapsePreview'):
    assert f'id="{feature}"' in template
for feature in ("'sun':sun_events(now)", "'modes':chart_modes", "DASHBOARD_CAPTURE_CRITICAL_SECONDS", "PREVIEW_NAME"):
    assert feature in dashboard
for guard in ("update_scene_analysis(image_array, measurement)", "record_keogram_slice(image_array, capture_time)", "scene_overlay_texts(measurement)"):
    assert guard in camera
loader = (root / 'loader.py').read_text(encoding='utf-8')
assert "'scene_analysis.py'" in loader and "'keogram.py'" in loader
assert 'schedule_periodic_timelapses()' in (root / 'runtime.py').read_text(encoding='utf-8')
assert 'renderScene' in template and 'id="sceneStats"' in template
print('PASS: scene analysis, keogram and periodic timelapse wiring')
print('PASS: dashboard views, trends, reports, archive and data coverage')
print('PASS: actionable health checks, timelapse reporting and CSV exports')
print('PASS: V50.3.5 runtime regression guards and camera service unit')
print('PASS: installer preserves existing camera service and rollback target')
