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
    script = script.replace('function lineChart(box,list,unit,dig,xfmt){', 'function lineChart(box,list,unit,dig,xfmt){drawn.push({series:list});')
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
 const e={tag,textContent:text,children:[],classList:{add(){},remove(){}},insertAdjacentHTML(){}};
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
        assert [v for v in graphs[period]['signal_min'] if v is not None] == [11]
        assert [v for v in graphs[period]['signal_max'] if v is not None] == [80]
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

def test_meteobridge_sunshine_minutes_become_hours():
    import datetime as dt
    import weather_station as ws
    v = ws.parse_meteobridge('temperature_c=5;sunshine_hours_today=354', dt.datetime.now(dt.timezone.utc))
    assert abs(v['sunshine_hours_today'] - 5.9) < 0.01

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
