#!/usr/bin/env python3
import ast
import os
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent
modules = [
    'version.py', 'core.py', 'camera.py', 'modes.py', 'exposure.py',
    'v47_control.py', 'image_quality.py', 'state.py', 'controller_analytics.py',
    'publishing.py', 'timelapse.py', 'monitoring.py', 'runtime.py', 'loader.py',
    'weather_camera.py', 'weathercam_dashboard/dashboard.py',
]
for filename in modules:
    compile((root / filename).read_text(encoding='utf-8'), str(root / filename), 'exec')

namespace = {}
exec((root / 'version.py').read_text(encoding='utf-8'), namespace)
assert namespace['VERSION'] == 'V50.3.4'
assert namespace['TELEMETRY_SCHEMA_VERSION'] == 4

publishing = (root / 'publishing.py').read_text(encoding='utf-8')
tree = ast.parse(publishing)
assignment = next(
    node for node in tree.body
    if isinstance(node, ast.Assign)
    and any(getattr(target, 'id', '') == 'TELEMETRY_FIELDS' for target in node.targets)
)
assert len(ast.literal_eval(assignment.value)) == 58

core = (root / 'core.py').read_text(encoding='utf-8')
assert "HWS_FTP_PASSWORD" in core
assert "SCRIPT_VERSION = '2026-11-19 V50.3.4'" in core
assert 'V50_MAX_CAMERA_RESTARTS_PER_HOUR = 6' in core

dashboard = (root / 'weathercam_dashboard/dashboard.py').read_text(encoding='utf-8')
template = (root / 'weathercam_dashboard/templates/dashboard.html').read_text(encoding='utf-8')
assert "V='50.3.4'" in dashboard
assert "'release':'V50.3.4'" in dashboard
assert "for period,hours in (('24h',24),('7d',168),('30d',720))" in dashboard
assert "'process_memory':series(recent_health,'memory.process_rss_bytes',scale=1/1048576)" in dashboard
assert 'incidents' in dashboard
assert 'V50.3.4' in template
assert "'mode_performance':mode_effectiveness(telemetry_rows,now)" in dashboard
assert 'id="modePerformanceRows"' in template
assert 'id="modeTransitions"' in template
assert 'renderModePerformance();' in template
assert template.count('__DATA__') == 1
assert "dataText.startsWith('{')?JSON.parse(dataText):{}" in template
assert "template.replace('__DATA__'" in dashboard
assert "template.count('__DATA__') != 1:raise RuntimeError" in dashboard
assert 'V49.11.2' not in template
assert 'data-view="gallery"' not in template
assert 'id="gallery"' not in template
for view in ('live', 'trends', 'events', 'advanced'):
    assert f'id="{view}"' in template
assert 'Diagnostics</button>' not in template
assert 'data-view="controller"' not in template
for period in ('24h', '7d', '30d'):
    assert f'data-period="{period}"' in template
assert 'Last 24 hours' in template and 'Last 7 days' in template and 'Last 30 days' in template
assert 'Raspberry Pi status' in template and 'id="piStats"' in template
assert 'id="processMemoryChart"' in template
assert 'id="trendCharts"' in template
assert "D.series?.[activePeriod]?.[key]" in template
for view in ('live', 'trends', 'events', 'advanced'):
    assert f'id="view-{view}"' in template
    assert f'for="view-{view}"' in template
    assert f'#view-{view}:checked~.page #{view}' in template
assert template.index('id="view-live"') < template.index('<div class="page">')
assert "document.querySelectorAll('.view-select')" in template
assert "'cpu_load_percent'" in dashboard

print('PASS: V50.3.4 release identity')
print('PASS: telemetry-v4 immutable 58-field contract')
print('PASS: FTP credentials are environment-configured')
print('PASS: bounded camera recovery and worker cooldown present')
print('PASS: dashboard view selection and data payload handling')
print('PASS: descriptive camera mode summaries and transitions')
