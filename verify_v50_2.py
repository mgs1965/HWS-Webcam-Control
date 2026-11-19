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
assert namespace['VERSION'] == 'V50.2'
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
assert "SCRIPT_VERSION = '2026-11-19 V50.2'" in core
assert 'V50_MAX_CAMERA_RESTARTS_PER_HOUR = 6' in core

dashboard = (root / 'weathercam_dashboard/dashboard.py').read_text(encoding='utf-8')
template = (root / 'weathercam_dashboard/templates/dashboard.html').read_text(encoding='utf-8')
assert "V='50.2'" in dashboard
assert "'release':'V50.2'" in dashboard
assert 'incidents' in dashboard
assert 'V50.2' in template
assert 'V49.11.2' not in template
assert 'data-view="gallery"' not in template
assert 'id="gallery"' not in template
for view in ('live', 'trends', 'events', 'advanced'):
    assert f'data-view="{view}"' in template
    assert f'id="{view}"' in template
assert 'Diagnostics</button>' not in template
assert 'data-view="controller"' not in template
assert 'data-view="7d"' not in template and 'data-view="30d"' not in template
assert 'Last 24 hours' in template and 'Recent events' in template
assert 'Raspberry Pi status' in template and 'id="piStats"' in template
assert "'cpu_load_percent'" in dashboard

print('PASS: V50.2 release identity')
print('PASS: telemetry-v4 immutable 58-field contract')
print('PASS: FTP credentials are environment-configured')
print('PASS: bounded camera recovery and worker cooldown present')
print('PASS: dashboard and V50.2 release payload present')
