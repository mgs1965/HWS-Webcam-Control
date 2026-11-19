#!/usr/bin/env python3
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent

def test_release_identity():
    namespace = {}
    exec((ROOT / 'version.py').read_text(encoding='utf-8'), namespace)
    assert namespace['VERSION'] == 'V50.3.2'
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

def test_dashboard_v50_3_2_payload():
    dashboard = (ROOT / 'weathercam_dashboard/dashboard.py').read_text(encoding='utf-8')
    template = (ROOT / 'weathercam_dashboard/templates/dashboard.html').read_text(encoding='utf-8')
    assert "V='50.3.2'" in dashboard
    assert "'release':'V50.3.2'" in dashboard
    assert "for period,hours in (('24h',24),('7d',168),('30d',720))" in dashboard
    assert 'incidents' in dashboard
    assert "'process_memory':series(recent_health,'memory.process_rss_bytes',scale=1/1048576)" in dashboard
    assert 'V49.11.2' not in template
    assert 'data-view="gallery"' not in template
    assert 'id="gallery"' not in template
    for view in ('live', 'trends', 'events', 'advanced'):
        assert f'id="{view}"' in template
    assert 'Diagnostics</button>' not in template
    assert 'data-view="controller"' not in template
    for period in ('24h', '7d', '30d'):
        assert f'data-period="{period}"' in template
    assert 'id="processMemoryChart"' in template
    assert 'id="trendCharts"' in template
    assert "D.series?.[activePeriod]?.[key]" in template
    assert template.count('__DATA__') == 1
    assert "dataText.startsWith('{')?JSON.parse(dataText):{}" in template
    assert "template.replace('__DATA__'" in dashboard
    assert "template.count('__DATA__') != 1:raise RuntimeError" in dashboard
    for view in ('live', 'trends', 'events', 'advanced'):
        assert f'id="view-{view}"' in template
        assert f'for="view-{view}"' in template
        assert f'#view-{view}:checked~.page #{view}' in template
    assert template.index('id="view-live"') < template.index('<div class="page">')
    assert '#view-live:checked~.page #live' in template
    assert '#view-trends:checked~.page #trends' in template
    assert "document.querySelectorAll('.view-select')" in template
    assert 'Last 24 hours' in template
    assert 'Last 7 days' in template
    assert 'Last 30 days' in template
    assert 'Recent events' in template
    assert 'Raspberry Pi status' in template
    assert 'id="piStats"' in template
    assert "'cpu_load_percent'" in dashboard
