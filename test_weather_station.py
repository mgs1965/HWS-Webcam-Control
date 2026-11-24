#!/usr/bin/env python3
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import weather_station as ws

NOW = datetime(2026, 11, 20, 17, 59, 40, tzinfo=timezone.utc)



def test_append_series_rolls_and_throttles(tmp_path):
    path = str(tmp_path / 'series.json')
    base = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    def sample(minutes, temp):
        return {'updated': (base + timedelta(minutes=minutes)).isoformat(), 'temperature_c': temp}
    assert ws.append_series(path, sample(0, 5.0))
    assert not ws.append_series(path, sample(2, 5.1))
    assert ws.append_series(path, sample(6, 5.2))
    assert ws.append_series(path, sample(60 * 25, 4.0))
    samples = json.load(open(path))['samples']
    assert [s['temperature_c'] for s in samples] == [4.0]



def test_atomic_write_roundtrip():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, 'sub', 'weather_station.json')
        ws.write_json_atomic(path, {'a': 1})
        assert json.load(open(path)) == {'a': 1}
        assert os.listdir(os.path.dirname(path)) == ['weather_station.json']



def test_run_loop_exits_after_consecutive_failures():
    original = ws.update_once
    ws.update_once = lambda output, **kwargs: None
    try:
        assert ws.run_loop('o', 60, max_failures=3, sleep=lambda s: None) == 1
    finally:
        ws.update_once = original



def test_meteobridge_parse_url_and_auth():
    import weather_station as ws
    now = datetime.now().astimezone()
    assert ws.meteobridge_url('192.168.0.65').startswith('http://192.168.0.65/cgi-bin/template.cgi?template=')
    assert 'wind0wind-act%3Dmph' in ws.meteobridge_url('http://192.168.0.65/')
    extra = ws.parse_meteobridge(
        'temperature_c=5.6;t0!3temp=8.1;th0!10hum=42;th0!10temp=7.2;th0!11temp=14.5',
        now,
    )
    assert extra['ground_temperature_c'] == 8.1
    assert extra['soil_wetness_cbar'] == 42
    assert extra['soil_temperature_c'] == 7.2
    assert extra['greenhouse_temperature_c'] == 14.5
    health = ws.parse_meteobridge(
        'temperature_c=5.6;data0!10num=12.5;data0!11num=864000;data0!12num=34;'
        'data0!13num=55;data0!14num=6.2;data0!15num=43;data0!16num=2;'
        'data0!17num=12.1;data0!18num=0.4',
        now,
    )
    assert health['cpu_load_percent'] == 12.5
    assert health['bridge_uptime_hours'] == 864000
    assert health['storage_usage_percent'] == 34
    assert health['ram_usage_percent'] == 55
    assert health['power_consumption_w'] == 6.2
    assert health['process_count'] == 43
    assert health['bridge_data_age_s'] == 2
    assert health['voltage_v'] == 12.1
    assert health['current_a'] == 0.4
    now = datetime.now().astimezone()
    data = ws.parse_meteobridge('temperature_c=5.6;humidity_percent=85.0;pressure_hpa=1000.7;wind_speed_mph=--;uv_index=0.0;rain_today_mm=1.2;bogus=1', now)
    assert data['temperature_c'] == 5.6 and data['rain_today_mm'] == 1.2 and data['source'] == 'meteobridge'
    assert 'wind_speed_mph' not in data and 'bogus' not in data
    assert ws.parse_meteobridge('temperature_c=--;humidity_percent=--', now) is None
    old = (ws.fetch_text, ws.METEOBRIDGE_URL, ws.METEOBRIDGE_PASSWORD)
    ws.METEOBRIDGE_URL = 'x'
    ws.METEOBRIDGE_PASSWORD = 'pw'
    seen = []
    ws.fetch_text = lambda url, timeout=10, headers=None: seen.append(headers) or 'temperature_c=5.6;humidity_percent=85' if 'template.cgi' in url else (_ for _ in ()).throw(OSError('down'))
    try:
        with tempfile.TemporaryDirectory() as directory:
            result = ws.update_once(os.path.join(directory, 'w.json'))
            assert result['temperature_c'] == 5.6
            assert seen[0]['Authorization'] == 'Basic bWV0ZW9icmlkZ2U6cHc='
    finally:
        ws.fetch_text, ws.METEOBRIDGE_URL, ws.METEOBRIDGE_PASSWORD = old


def test_extra_sensor_template_and_persistence(tmp_path, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    template = parse_qs(urlsplit(ws.meteobridge_url('bridge')).query)['template'][0]
    fields = {
        'ground_temperature_c': 't3temp', 'soil_wetness_cbar': 'soil0hum',
        'soil_temperature_c': 'soil0temp', 'greenhouse_temperature_c': 'soil1temp',
        'cpu_load_percent': 'data10num', 'bridge_uptime_hours': 'data11num',
        'storage_usage_percent': 'data12num', 'ram_usage_percent': 'data13num',
        'power_consumption_w': 'data14num', 'process_count': 'data15num',
        'bridge_data_age_s': 'data16num', 'voltage_v': 'data17num', 'current_a': 'data18num',
    }
    for key, sensor in fields.items():
        assert f'{key}=[{sensor}-act]' in template
    assert template.count('bridge_data_age_s=') == 1
    data = ws.parse_meteobridge('temperature_c=5;ground_temperature_c=0;soil_wetness_cbar=--;'
                                'cpu_load_percent=25;bridge_uptime_hours=86400;bridge_data_age_s=0;current_a=0.123', NOW)
    assert data['ground_temperature_c'] == 0 and 'soil_wetness_cbar' not in data
    assert data['current_a'] == 0.123 and data['bridge_data_age_s'] == 0
    monkeypatch.setattr(ws, 'LIVE_PATH', str(tmp_path / 'live.json'))
    monkeypatch.setattr(ws, 'LIVE_UPLOAD_SECONDS', 0)
    assert ws.publish_live(data)
    assert json.loads((tmp_path / 'live.json').read_text())['current_a'] == 0.123
    ws.append_series(str(tmp_path / 'series.json'), data)
    assert json.loads((tmp_path / 'series.json').read_text())['samples'][0]['cpu_load_percent'] == 25
    daily_path = str(tmp_path / 'daily.json')
    for load in [1.01, 1.02, 1.02]:
        ws.record_daily({**data, 'cpu_load_percent': load}, daily_path)
    day = json.loads((tmp_path / 'daily.json').read_text())['days']['2026-11-20']
    assert abs(day['cpu_load_avg'] - (1.01 + 1.02 + 1.02) / 3) < 1e-10
    assert day['uptime_last'] == 86400


def test_centibars_hours_and_signal_extremes(tmp_path):
    template = dict(ws.METEOBRIDGE_FIELDS)
    assert template['signal_min'] == 'th0signal-min5'
    assert template['signal_max'] == 'th0signal-max5'
    assert template['signal_day_min'] == 'th0signal-dmin'
    assert template['signal_day_max'] == 'th0signal-dmax'
    data = ws.parse_meteobridge(
        'temperature_c=5;soil_wetness_cbar=175;bridge_uptime_hours=48;'
        'signal_min=20;signal_max=75;signal_day_min=5;signal_day_max=90', NOW)
    assert data['soil_wetness_cbar'] == 175
    assert data['bridge_uptime_hours'] == 48
    assert (data['signal_min'], data['signal_max']) == (20, 75)
    assert 'soil_wetness_cbar' not in ws.parse_meteobridge('temperature_c=5;soil_wetness_cbar=201', NOW)
    series = str(tmp_path / 'series.json')
    ws.append_series(series, data)
    sample = json.loads((tmp_path / 'series.json').read_text())['samples'][0]
    assert (sample['signal_min'], sample['signal_max']) == (20, 75)
    path = str(tmp_path / 'daily.json')
    ws.record_daily(data, path)
    ws.record_daily({**data, 'signal_day_min': 3, 'signal_day_max': 92}, path)
    day = json.loads((tmp_path / 'daily.json').read_text())['days']['2026-11-20']
    assert (day['signal_min'], day['signal_max'], day['uptime_last']) == (3, 92, 48)
    assert dict(ws.backfill_expressions(7))['signal_min'] == 'th0signal-min@D7'
    assert dict(ws.backfill_expressions(7))['signal_max'] == 'th0signal-max@D7'
    assert ws.parse_backfill_day('signal_min=4;signal_max=91') == {'signal_min': 4, 'signal_max': 91}


def test_new_sensors_live_daily_and_backfill(tmp_path, monkeypatch):
    fields = dict(ws.METEOBRIDGE_FIELDS)
    assert fields['base_board_temperature_c'] == 'thb9temp-act'
    assert fields['rf_board_temperature_c'] == 'thb0temp-act'
    data = ws.parse_meteobridge('temperature_c=5;base_board_temperature_c=35.5;rf_board_temperature_c=42;ground_temperature_c=7;soil_wetness_cbar=70', NOW)
    monkeypatch.setattr(ws, 'LIVE_PATH', str(tmp_path / 'live.json'))
    monkeypatch.setattr(ws, 'LIVE_UPLOAD_SECONDS', 0)
    assert ws.publish_live(data)
    assert json.loads((tmp_path / 'live.json').read_text())['base_board_temperature_c'] == 35.5
    series = str(tmp_path / 'series.json')
    ws.append_series(series, data)
    assert json.loads((tmp_path / 'series.json').read_text())['samples'][0]['rf_board_temperature_c'] == 42
    daily = str(tmp_path / 'daily.json')
    ws.record_daily(data, daily)
    ws.record_daily({**data, 'base_board_temperature_c': 37.5}, daily)
    day = json.loads((tmp_path / 'daily.json').read_text())['days']['2026-11-20']
    assert day['base_board_temp_avg_c'] == 36.5
    assert day['rf_board_temp_avg_c'] == 42
    assert day['soil_wetness_avg_cbar'] == 70
    expressions = dict(ws.backfill_expressions(1))
    for key, sensor in [('base_board_temp_avg_c', 'thb9temp'), ('rf_board_temp_avg_c', 'thb0temp'),
                        ('ground_temp_avg_c', 't3temp'), ('soil_wetness_avg_cbar', 'soil0hum'),
                        ('soil_temp_avg_c', 'soil0temp'), ('greenhouse_temp_avg_c', 'soil1temp')]:
        assert expressions[key] == f'{sensor}-avg@D1'
    archive = tmp_path / 'archive.json'
    archive.write_text(json.dumps({'days': {'2026-11-19': {'bf': 3, 'rain_mm': 4, 'rf_board_temp_avg_c': 38}}}))
    calls = []
    def fetch(url):
        calls.append(url)
        return 'base_board_temp_avg_c=33;rf_board_temp_avg_c=--;soil_wetness_avg_cbar=75'
    result = ws.backfill_archive('bridge', str(archive), days=1, today=NOW.date(), fetch=fetch, sleep=lambda _: None)
    saved = json.loads(archive.read_text())['days']['2026-11-19']
    assert result['added'] == 1 and len(calls) == 1
    assert saved == {'bf': 4, 'rain_mm': 4, 'rf_board_temp_avg_c': 38, 'base_board_temp_avg_c': 33, 'soil_wetness_avg_cbar': 75}
    assert ws.backfill_archive('bridge', str(archive), days=1, today=NOW.date(), fetch=fetch, sleep=lambda _: None)['added'] == 0


def test_local_history_from_meteobridge(tmp_path):
    import weather_station as ws
    old = (ws.fetch_text, ws.METEOBRIDGE_URL, ws.MINUTE_PATH, ws.DAILY_LOG_PATH)
    ws.METEOBRIDGE_URL = 'x'
    ws.MINUTE_PATH, ws.DAILY_LOG_PATH = str(tmp_path / 'm.json'), str(tmp_path / 'd.json')
    base = datetime.now().astimezone() - timedelta(minutes=60)
    clock = {'now': base}
    reading = {'t': 5.0}
    calls = []
    ws.fetch_text = lambda url, timeout=10, headers=None: calls.append(url) or f"temperature_c={reading['t']};humidity_percent=80;pressure_hpa=1000;wind_gust_mph=4"
    real = ws.datetime
    ws.datetime = type('D', (), {'now': staticmethod(lambda: clock['now']), 'fromisoformat': staticmethod(real.fromisoformat)})
    try:
        for minute in range(61):
            clock['now'] = base + timedelta(minutes=minute)
            reading['t'] = 5.0 + minute * 0.02
            result = ws.update_once(str(tmp_path / 'w.json'))
        assert all('template.cgi' in url for url in calls)
        assert result['source'] == 'meteobridge' and result['temp_change_1h_c'] == 1.2
        assert result['wind_gust_max_1h_mph'] == 4
        day = json.loads((tmp_path / 'd.json').read_text())['days']
        assert list(day.values())[0]['temp_max_c'] >= 6.2
        clock['now'] = base + timedelta(days=2)
        (tmp_path / 'd.json').write_text(json.dumps({'days': {(clock['now'].date() - timedelta(days=1)).isoformat(): {'temp_max_c': 9.0, 'temp_min_c': 1.0}}}))
        history = ws.update_history(str(tmp_path / 'h.json'))
        assert history['daily'][-1]['temp_max_c'] == 9.0
    finally:
        ws.datetime = real
        (ws.fetch_text, ws.METEOBRIDGE_URL, ws.MINUTE_PATH, ws.DAILY_LOG_PATH) = old



def test_publish_live_writes_subset_and_throttles(tmp_path, monkeypatch):
    uploads = []
    monkeypatch.setattr(ws, 'LIVE_PATH', str(tmp_path / 'live.json'))
    monkeypatch.setattr(ws, 'LIVE_UPLOAD_SECONDS', 120)
    monkeypatch.setitem(ws._live_state, 'next', 0.0)
    monkeypatch.setattr(ws, 'upload_live', lambda path: uploads.append(path) or True)
    data = {'updated': 'x', 'temperature_c': 5.0, 'secret_internal': 1}
    assert ws.publish_live(data, clock=lambda: 1000.0)
    assert ws.publish_live(data, clock=lambda: 1060.0)
    assert ws.publish_live(data, clock=lambda: 1121.0)
    written = json.load(open(tmp_path / 'live.json'))
    assert written == {'updated': 'x', 'temperature_c': 5.0}
    assert len(uploads) == 2


def test_retry_transient_http_and_timeout_but_not_auth(monkeypatch):
    from urllib.error import HTTPError
    import pytest
    attempts, delays = [], []
    def flaky(url, timeout, headers):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise HTTPError(url, 504, 'Gateway Timeout', {}, None)
        if len(attempts) == 2:
            raise TimeoutError('timed out')
        return 'temperature_c=7'
    monkeypatch.setattr(ws, 'fetch_text', flaky)
    assert ws.fetch_with_retry('http://bridge', 20, 2, 3, sleep=delays.append) == 'temperature_c=7'
    assert attempts == [20, 20, 20] and delays == [3, 3]
    monkeypatch.setattr(ws, 'fetch_text', lambda url, timeout, headers: (_ for _ in ()).throw(HTTPError(url, 401, 'Unauthorized', {}, None)))
    with pytest.raises(HTTPError):
        ws.fetch_with_retry('http://bridge', 20, 2, 3, sleep=lambda _: pytest.fail('must not retry authentication failure'))


def test_backfill_paces_empty_days_and_saves_on_failure(tmp_path):
    path = tmp_path / 'archive.json'
    calls, delays = [], []
    def fetch(url):
        calls.append(url)
        if len(calls) == 1:
            return 'temp_max_c=10;temp_min_c=2'
        if len(calls) == 2:
            return 'temp_max_c=--;temp_min_c=--'
        raise TimeoutError('timed out')
    result = ws.backfill_archive('bridge', str(path), days=5, today=NOW.date(), fetch=fetch, sleep=delays.append, delay=2)
    assert delays == [2, 2, 2] and result['stopped'] == '2026-11-17'
    assert json.loads(path.read_text())['days']['2026-11-19']['temp_max_c'] == 10


def test_backfill_saves_on_interrupt(tmp_path):
    calls = []
    def fetch(url):
        calls.append(url)
        if len(calls) == 1:
            return 'temp_max_c=10;temp_min_c=2'
        raise KeyboardInterrupt
    path = tmp_path / 'archive.json'
    result = ws.backfill_archive('bridge', str(path), days=4, today=NOW.date(), fetch=fetch, sleep=lambda _: None)
    assert result['stopped'] == '2026-11-18'
    assert '2026-11-19' in json.loads(path.read_text())['days']


def test_number_and_bounds_reject_junk():
    assert ws._number('3.5') == 3.5 and ws._number('nan') is None and ws._number('x') is None and ws._number(None) is None
    assert ws._bounded('wind_gust_mph', 20.123) == 20.12
    assert ws._bounded('wind_gust_mph', 900) is None and ws._bounded('wind_gust_mph', None) is None


def test_backfill_day_parsing_filters_and_converts():
    day = ws.parse_backfill_day('temp_max_c=21.5;rain_mm=nope;sunshine_min=90;unknown=5\ntemp_min_c=-300')
    assert day.get('temp_max_c') == 21.5 and day.get('sunshine_hours') == 1.5
    assert 'rain_mm' not in day and 'unknown' not in day and 'temp_min_c' not in day
    assert ws.parse_backfill_day(None) == {}


def test_backfill_expressions_insert_day_offset_before_unit():
    exprs = dict(ws.backfill_expressions(3))
    assert all('@D3' in e for e in exprs.values())
    assert any(e.endswith(('=mph', '=mm')) or '=' not in e for e in exprs.values())


def test_local_trends_need_forty_minutes_of_data():
    base = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    def run(minutes):
        return [{'t': (base + timedelta(minutes=m)).isoformat(), 'temperature_c': 10 + m / 60, 'wind_gust_mph': m % 7}
                for m in range(0, minutes, 2)]
    assert ws.local_trends(run(10)) == {}
    longer = ws.local_trends(run(60))
    assert longer['temp_change_1h_c'] > 0 and longer['wind_gust_max_1h_mph'] == 6
    assert ws.local_trends([{'t': 'bad'}] * 20) == {}


def test_record_daily_keeps_extremes_for_the_day(tmp_path):
    path = str(tmp_path / 'daily.json')
    for temp, rain in ((8.0, 0.0), (15.5, 1.2), (11.0, 1.0)):
        ws.record_daily({'updated': '2026-11-20T12:00:00+00:00', 'temperature_c': temp, 'rain_today_mm': rain}, path)
    day = json.load(open(path))['days']['2026-11-20']
    assert day['temp_max_c'] == 15.5 and day['temp_min_c'] == 8.0 and day['rain_mm'] == 1.2
