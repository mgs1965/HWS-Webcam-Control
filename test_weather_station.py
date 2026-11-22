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
    assert ws.meteobridge_url('192.168.0.65').startswith('http://192.168.0.65/cgi-bin/template.cgi?template=')
    assert 'wind0wind-act%3Dmph' in ws.meteobridge_url('http://192.168.0.65/')
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
