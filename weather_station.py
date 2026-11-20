#!/usr/bin/env python3
"""Weather Display clientraw.txt fetcher.

Standalone producer for the JSON file the camera already consumes
(HWS_WEATHER_DATA_PATH, default /mnt/weathercam/logs/weather_station.json).
It never touches camera control. Missing, stale or malformed data is never
written, so the camera simply treats the station as unavailable.

Usage:
    CLIENTRAW_URL=https://example.org/clientraw.txt python3 weather_station.py --once
    CLIENTRAW_URL=... python3 weather_station.py --interval 60
"""
import argparse
import json
import math
import os
import sys
import tempfile
import time
import urllib.request
from datetime import datetime

KNOTS_TO_MPH = 1.150779
MIN_FETCH_INTERVAL_SECONDS = 30
MAX_AGE_SECONDS = 900
MAX_BYTES = 65536
MIN_FIELDS = 100

# Standard Weather Display clientraw.txt field positions (0-indexed).
IDX_WIND_AVG_KT, IDX_WIND_GUST_KT, IDX_WIND_DIR = 1, 2, 3
IDX_TEMP_C, IDX_HUMIDITY, IDX_PRESSURE_HPA = 4, 5, 6
IDX_RAIN_TODAY_MM, IDX_RAIN_RATE = 7, 10
IDX_HOUR, IDX_MINUTE, IDX_SECOND, IDX_STATION = 29, 30, 31, 32
IDX_DEW_POINT_C, IDX_DATE = 72, 74

# clientraw reports rain rate per minute; the camera expects mm/h.
RAIN_RATE_TO_MM_H = 60.0

LIMITS = {
    'temperature_c': (-60.0, 60.0),
    'humidity_percent': (0.0, 100.0),
    'pressure_hpa': (850.0, 1100.0),
    'wind_speed_mph': (0.0, 250.0),
    'wind_gust_mph': (0.0, 250.0),
    'wind_direction_deg': (0.0, 360.0),
    'rain_rate_mm_h': (0.0, 500.0),
    'rain_today_mm': (0.0, 2000.0),
    'dew_point_c': (-60.0, 60.0),
}


def _number(token):
    try:
        value = float(token)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _bounded(key, value):
    if value is None:
        return None
    low, high = LIMITS[key]
    return round(value, 2) if low <= value <= high else None


def parse_clientraw(text, now):
    """Parse a clientraw.txt body into the camera's weather JSON dict.

    `now` is a timezone-aware datetime in the station's local time zone.
    Returns None when the file is malformed or older than MAX_AGE_SECONDS.
    Placeholder '-' fields are treated as missing, never as zero.
    """
    tokens = (text or '').split()
    if len(tokens) < MIN_FIELDS or tokens[0] != '12345':
        return None
    try:
        stamp = datetime.strptime(f'{tokens[IDX_DATE]} {int(tokens[IDX_HOUR])}:{int(tokens[IDX_MINUTE])}:{int(tokens[IDX_SECOND])}', '%m/%d/%Y %H:%M:%S')
    except (ValueError, IndexError):
        return None
    updated = stamp.replace(tzinfo=now.tzinfo)
    age = (now - updated).total_seconds()
    if age > MAX_AGE_SECONDS or age < -60:
        return None

    def field(index):
        return _number(tokens[index]) if index < len(tokens) else None

    def scaled(index, factor):
        value = field(index)
        return None if value is None else value * factor

    raw = {
        'temperature_c': field(IDX_TEMP_C),
        'humidity_percent': field(IDX_HUMIDITY),
        'pressure_hpa': field(IDX_PRESSURE_HPA),
        'wind_speed_mph': scaled(IDX_WIND_AVG_KT, KNOTS_TO_MPH),
        'wind_gust_mph': scaled(IDX_WIND_GUST_KT, KNOTS_TO_MPH),
        'wind_direction_deg': field(IDX_WIND_DIR),
        'rain_rate_mm_h': scaled(IDX_RAIN_RATE, RAIN_RATE_TO_MM_H),
        'rain_today_mm': field(IDX_RAIN_TODAY_MM),
        'dew_point_c': field(IDX_DEW_POINT_C),
    }
    values = {key: _bounded(key, value) for key, value in raw.items()}
    values = {key: value for key, value in values.items() if value is not None}
    if not any(key in values for key in ('temperature_c', 'humidity_percent', 'pressure_hpa')):
        return None
    values['updated'] = updated.isoformat()
    if IDX_STATION < len(tokens):
        values['station'] = tokens[IDX_STATION].replace('_', ' ')
    return values


def fetch_text(url, timeout=10):
    if not url.lower().startswith(('http://', 'https://')):
        raise ValueError('CLIENTRAW_URL must be http(s)')
    request = urllib.request.Request(url, headers={'User-Agent': 'HWS-Webcam-Control weather_station/1'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(MAX_BYTES).decode('utf-8', errors='replace')


def write_json_atomic(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, prefix='.weather_station_', suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as output:
            json.dump(data, output, separators=(',', ':'))
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


FETCH_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
MAX_CONSECUTIVE_FAILURES = 10


def log(message):
    print(f'[WEATHER STATION] {message}', file=sys.stderr, flush=True)


def update_once(url, output_path, attempts=FETCH_ATTEMPTS, retry_delay=RETRY_DELAY_SECONDS, sleep=time.sleep):
    """Fetch, parse and publish once, retrying transient network errors.

    Returns the dict written, or None. Stale or malformed files are not
    retried (the station itself has to recover) and are never written.
    """
    for attempt in range(1, attempts + 1):
        try:
            text = fetch_text(url)
        except (OSError, ValueError) as error:
            log(f'fetch failed (attempt {attempt}/{attempts}): {error}')
            if attempt < attempts:
                sleep(retry_delay * attempt)
            continue
        data = parse_clientraw(text, datetime.now().astimezone())
        if data is None:
            log('clientraw malformed or stale; not publishing')
            return None
        try:
            write_json_atomic(output_path, data)
        except OSError as error:
            log(f'could not write {output_path}: {error}')
            return None
        return data
    return None


def run_loop(url, output_path, interval, max_failures=MAX_CONSECUTIVE_FAILURES, sleep=time.sleep):
    """Poll forever; return 1 after max_failures consecutive failures so systemd restarts us."""
    failures = 0
    while True:
        if update_once(url, output_path):
            if failures:
                log(f'recovered after {failures} failed cycle(s)')
            failures = 0
        else:
            failures += 1
            if failures >= max_failures:
                log(f'{failures} consecutive failures; exiting for supervisor restart')
                return 1
        sleep(interval)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--url', default=os.getenv('CLIENTRAW_URL'))
    parser.add_argument('--output', default=os.getenv('HWS_WEATHER_DATA_PATH', '/mnt/weathercam/logs/weather_station.json'))
    parser.add_argument('--interval', type=int, default=0, help='poll every N seconds (minimum %d); omit for a single run' % MIN_FETCH_INTERVAL_SECONDS)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    if not args.url:
        parser.error('set CLIENTRAW_URL or pass --url')
    if args.once or not args.interval:
        return 0 if update_once(args.url, args.output) else 1
    return run_loop(args.url, args.output, max(MIN_FETCH_INTERVAL_SECONDS, args.interval))


if __name__ == '__main__':
    sys.exit(main())
