#!/usr/bin/env python3
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import weather_station as ws

SAMPLE = ('12345 2.72 2.72 0 5.6 88 1012.4 0.0 64.0 643.8 0.00 0.00 17.9 66 7.9 - - - 0 4.0 5.6 1.5 - - - - - 0 - 17 59 23 '
          'Harpenden_Weather_Station 0 0 20 11 - - - - - - - 5.6 - 8.5 3.4 _ - 1.1 0.4 1.6 1.5 2.2 2.6 4.0 3.7 - - - - - - - - - - '
          '0.0 0.4 0.4 6.4 3.8 720 11/20/2026 ' + '- ' * 60 + '!!C10.37O!!\n')
NOW = datetime(2026, 11, 20, 17, 59, 40, tzinfo=timezone.utc)


def test_parse_solar_and_uv():
    tokens = SAMPLE.split(' ')
    tokens[79], tokens[127] = '5.5', '612'
    data = ws.parse_clientraw(' '.join(tokens), NOW)
    assert data['uv_index'] == 5.5 and data['solar_radiation_wm2'] == 612.0


def test_parse_lightning_and_gusts():
    tokens = SAMPLE.split(' ')
    tokens[33], tokens[71], tokens[114], tokens[118], tokens[133] = '12', '20', '3', '8', '10'
    data = ws.parse_clientraw(' '.join(tokens), NOW)
    assert data['lightning_strikes_today'] == 12 and data['lightning_strikes_last_min'] == 3
    assert data['lightning_distance'] == 8 and data['wind_gust_max_today_mph'] == round(20 * ws.KNOTS_TO_MPH, 2)
    assert data['wind_gust_max_1h_mph'] == round(10 * ws.KNOTS_TO_MPH, 2)


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


def test_parse_sample():
    data = ws.parse_clientraw(SAMPLE, NOW)
    assert data['temperature_c'] == 5.6
    assert data['humidity_percent'] == 88
    assert data['pressure_hpa'] == 1012.4
    assert data['dew_point_c'] == 3.8
    assert data['wind_speed_mph'] == round(2.72 * ws.KNOTS_TO_MPH, 2)
    assert data['rain_rate_mm_h'] == 0.0
    assert data['station'] == 'Harpenden Weather Station'
    assert data['updated'] == '2026-11-20T17:59:23+00:00'


def test_rejects_stale_malformed_and_empty():
    assert ws.parse_clientraw(SAMPLE, datetime(2026, 11, 20, 19, 0, tzinfo=timezone.utc)) is None
    assert ws.parse_clientraw('garbage', NOW) is None
    assert ws.parse_clientraw('', NOW) is None
    assert ws.parse_clientraw(SAMPLE.replace('12345', '99999', 1), NOW) is None


def test_missing_and_out_of_range_values_are_dropped():
    tokens = SAMPLE.split()
    tokens[ws.IDX_HUMIDITY] = '-'
    tokens[ws.IDX_PRESSURE_HPA] = '5000'
    data = ws.parse_clientraw(' '.join(tokens), NOW)
    assert 'humidity_percent' not in data
    assert 'pressure_hpa' not in data
    assert data['temperature_c'] == 5.6


def test_atomic_write_roundtrip():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, 'sub', 'weather_station.json')
        ws.write_json_atomic(path, {'a': 1})
        assert json.load(open(path)) == {'a': 1}
        assert os.listdir(os.path.dirname(path)) == ['weather_station.json']


def test_update_once_retries_then_succeeds():
    calls = []
    original = ws.fetch_text
    def flaky(url, timeout=10):
        calls.append(1)
        if len(calls) < 3:
            raise OSError('boom')
        return SAMPLE
    ws.fetch_text = flaky
    ws.datetime = type('D', (), {'now': staticmethod(lambda: NOW), 'strptime': staticmethod(datetime.strptime)})
    try:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'w.json')
            assert ws.update_once('http://x', path, sleep=lambda s: None)
            assert len(calls) == 3 and os.path.exists(path)
            calls.clear()
            ws.fetch_text = lambda url, timeout=10: (_ for _ in ()).throw(OSError('down'))
            assert ws.update_once('http://x', path + '2', sleep=lambda s: None) is None
            assert not os.path.exists(path + '2')
    finally:
        ws.fetch_text = original
        ws.datetime = datetime


def test_run_loop_exits_after_consecutive_failures():
    original = ws.update_once
    ws.update_once = lambda url, output, **kwargs: None
    try:
        assert ws.run_loop('u', 'o', 60, max_failures=3, sleep=lambda s: None) == 1
    finally:
        ws.update_once = original


def _hour_text(pressure_start=1011.0):
    blocks = {k: ['-'] * 60 for k in ws.HOUR_BLOCKS}
    for i in range(55):
        blocks['temp_c'][i] = str(6.0 - i * 0.01)
        blocks['humidity'][i] = str(80 + i // 10)
        blocks['pressure_hpa'][i] = str(round(pressure_start + i * 0.02, 2))
        blocks['gust_kt'][i] = '2.0'
    tokens = ['12345'] + ['-'] * 600
    for name, start in ws.HOUR_BLOCKS.items():
        tokens[start:start + 60] = blocks[name]
    tokens += ['0'] * 100
    return ' '.join(tokens)


def test_hour_trends():
    trends = ws.hour_trends(ws.parse_clientrawhour(_hour_text()))
    assert trends['temp_change_1h_c'] == -0.54
    assert trends['humidity_change_1h'] == 5.0
    assert trends['pressure_change_1h_hpa'] == 1.08
    assert trends['wind_gust_max_1h_mph'] == round(2.0 * ws.KNOTS_TO_MPH, 2)
    assert ws.hour_trends({'temp_c': [None] * 60}) == {}
    assert ws.parse_clientrawhour('12345 1 2') is None


def test_daily_and_extra():
    tokens = ['12345'] + ['-'] * 399
    for name, start in ws.DAILY_BLOCKS.items():
        for i in range(30):
            tokens[start + i] = str(i)
    tokens[ws.DAILY_BLOCKS['temp_min_c'] + 29] = '-'
    days = ws.parse_clientrawdaily(' '.join(tokens), datetime(2026, 11, 20).date())
    assert len(days) == 30 and days[-1]['date'] == '2026-11-19' and days[-1]['temp_max_c'] == 29.0
    assert 'temp_min_c' not in days[-1]
    extra = ['12345'] + ['-'] * 300
    extra[ws.EXTRA_YEAR_START:ws.EXTRA_YEAR_START + 6] = '40.2 16 44 13 08 2026'.split()
    extra[ws.EXTRA_YEAR_START + 6:ws.EXTRA_YEAR_START + 12] = '-5.8 08 00 06 01 2026'.split()
    records = ws.parse_clientrawextra(' '.join(extra))
    assert records['temp_max_c'] == {'value': 40.2, 'when': '2026-08-13T16:44:00'}
    assert records['temp_min_c']['value'] == -5.8 and 'pressure_min_hpa' not in records


def test_sibling_url():
    assert ws.sibling_url('http://a/Live/clientraw.txt', 'clientrawhour.txt') == 'http://a/Live/clientrawhour.txt'
    assert ws.sibling_url('http://a/other.txt', 'clientrawhour.txt') is None


if __name__ == '__main__':
    for name, function in list(globals().items()):
        if name.startswith('test_'):
            function()
    print('weather_station tests passed')


def test_meteobridge_parse_url_and_fallback():
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
    ws.COMPARE_PATH = None
    seen = []
    ws.fetch_text = lambda url, timeout=10, headers=None: seen.append(headers) or 'temperature_c=5.6;humidity_percent=85' if 'template.cgi' in url else (_ for _ in ()).throw(OSError('down'))
    try:
        with tempfile.TemporaryDirectory() as directory:
            result = ws.update_once('http://clientraw/clientraw.txt', os.path.join(directory, 'w.json'), sleep=lambda s: None)
            assert result['temperature_c'] == 5.6
            assert seen[0]['Authorization'] == 'Basic bWV0ZW9icmlkZ2U6cHc='
    finally:
        ws.fetch_text, ws.METEOBRIDGE_URL, ws.METEOBRIDGE_PASSWORD = old


def test_clientraw_off_uses_local_history(tmp_path):
    import weather_station as ws
    old = (ws.fetch_text, ws.METEOBRIDGE_URL, ws.COMPARE_PATH, ws.CLIENTRAW_ENABLED, ws.MINUTE_PATH, ws.DAILY_LOG_PATH)
    ws.METEOBRIDGE_URL, ws.COMPARE_PATH, ws.CLIENTRAW_ENABLED = 'x', None, False
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
            result = ws.update_once('http://c/clientraw.txt', str(tmp_path / 'w.json'), sleep=lambda s: None)
        assert all('template.cgi' in url for url in calls)
        assert result['source'] == 'meteobridge' and result['temp_change_1h_c'] == 1.2
        assert result['wind_gust_max_1h_mph'] == 4
        day = json.loads((tmp_path / 'd.json').read_text())['days']
        assert list(day.values())[0]['temp_max_c'] >= 6.2
        clock['now'] = base + timedelta(days=2)
        (tmp_path / 'd.json').write_text(json.dumps({'days': {(clock['now'].date() - timedelta(days=1)).isoformat(): {'temp_max_c': 9.0, 'temp_min_c': 1.0}}}))
        history = ws.update_history('http://c/clientraw.txt', str(tmp_path / 'h.json'))
        assert history['daily'][-1]['temp_max_c'] == 9.0
    finally:
        ws.datetime = real
        (ws.fetch_text, ws.METEOBRIDGE_URL, ws.COMPARE_PATH, ws.CLIENTRAW_ENABLED, ws.MINUTE_PATH, ws.DAILY_LOG_PATH) = old


def test_seed_local_history_from_clientraw(tmp_path):
    old = (ws.fetch_text, ws.MINUTE_PATH, ws.DAILY_LOG_PATH)
    ws.MINUTE_PATH, ws.DAILY_LOG_PATH = str(tmp_path / 'm.json'), str(tmp_path / 'd.json')
    hour = ['12345'] + [str(v) for blk in (10, 12, 180, 5, 80, 1000) for v in [blk] * 60] + ['0'] * 20
    daily = ['12345', '0'] + ['0'] * 130
    for i in range(30):
        daily[2 + i], daily[33 + i], daily[95 + i] = str(10 + i), str(i), str(990 + i)
    files = {'clientrawhour.txt': ' '.join(hour), 'clientrawdaily.txt': ' '.join(daily)}
    ws.fetch_text = lambda url, timeout=10, headers=None: files[url.rsplit('/', 1)[1]]
    now = datetime.now().astimezone().replace(second=30, microsecond=0)
    try:
        added = ws.seed_local_history('http://c/clientraw.txt', now)
        assert added['minutes'] == 59 and added['days'] == 30
        samples = json.loads((tmp_path / 'm.json').read_text())['samples']
        assert samples[0]['temperature_c'] == 5.0 and abs(samples[0]['wind_speed_mph'] - 10 * ws.KNOTS_TO_MPH) < 0.01
        assert ws.seed_local_history('http://c/clientraw.txt', now) == {'minutes': 0, 'days': 0}
        assert len(json.loads((tmp_path / 'd.json').read_text())['days']) == 30
    finally:
        ws.fetch_text, ws.MINUTE_PATH, ws.DAILY_LOG_PATH = old
