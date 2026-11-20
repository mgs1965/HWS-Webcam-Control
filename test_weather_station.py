#!/usr/bin/env python3
import json
import os
import tempfile
from datetime import datetime, timezone

import weather_station as ws

SAMPLE = ('12345 2.72 2.72 0 5.6 88 1012.4 0.0 64.0 643.8 0.00 0.00 17.9 66 7.9 - - - 0 4.0 5.6 1.5 - - - - - 0 - 17 59 23 '
          'Harpenden_Weather_Station 0 0 20 11 - - - - - - - 5.6 - 8.5 3.4 _ - 1.1 0.4 1.6 1.5 2.2 2.6 4.0 3.7 - - - - - - - - - - '
          '0.0 0.4 0.4 6.4 3.8 720 11/20/2026 ' + '- ' * 60 + '!!C10.37O!!\n')
NOW = datetime(2026, 11, 20, 17, 59, 40, tzinfo=timezone.utc)


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
    ws.update_once = lambda url, output: None
    try:
        assert ws.run_loop('u', 'o', 60, max_failures=3, sleep=lambda s: None) == 1
    finally:
        ws.update_once = original


if __name__ == '__main__':
    for name, function in list(globals().items()):
        if name.startswith('test_'):
            function()
    print('weather_station tests passed')
