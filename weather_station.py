#!/usr/bin/env python3
"""Weather Display clientraw.txt fetcher.

Standalone producer for the JSON file the camera already consumes
(HWS_WEATHER_DATA_PATH, default /mnt/weathercam/logs/weather_station.json),
enriched with 1-hour trends from clientrawhour.txt, plus a history file
(HWS_WEATHER_HISTORY_PATH) with 30 daily extremes from clientrawdaily.txt and
year records from clientrawextra.txt. Sibling files are found next to the URL.
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
from datetime import datetime, timedelta

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
IDX_UV_INDEX, IDX_SOLAR_WM2 = 34, 127

# clientraw reports rain rate per minute; the camera expects mm/h.
RAIN_RATE_TO_MM_H = 60.0

HISTORY_INTERVAL_SECONDS = 1800
HOUR_BLOCK = 60
# clientrawhour.txt: consecutive 60-minute blocks, oldest first, '-' = no sample.
HOUR_BLOCKS = {'wind_kt': 1, 'gust_kt': 61, 'wind_dir': 121, 'temp_c': 181, 'humidity': 241, 'pressure_hpa': 301}
# clientrawdaily.txt: 30 daily values per block (last = yesterday), one '-' padding token before each block.
DAILY_DAYS = 30
DAILY_BLOCKS = {'temp_max_c': 2, 'temp_min_c': 33, 'pressure_min_hpa': 95}
# clientrawextra.txt: year records as (value, hour, minute, day, month, year) groups.
EXTRA_YEAR_START = 187
EXTRA_YEAR_RECORDS = ('temp_max_c', 'temp_min_c', 'wind_gust_record', 'rain_record', 'pressure_min_hpa', 'pressure_max_hpa')

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
    'uv_index': (0.0, 20.0),
    'solar_radiation_wm2': (0.0, 1800.0),
    'temp_change_1h_c': (-40.0, 40.0),
    'humidity_change_1h': (-100.0, 100.0),
    'pressure_change_1h_hpa': (-50.0, 50.0),
    'wind_gust_max_1h_mph': (0.0, 250.0),
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
        'uv_index': field(IDX_UV_INDEX),
        'solar_radiation_wm2': field(IDX_SOLAR_WM2),
    }
    values = {key: _bounded(key, value) for key, value in raw.items()}
    values = {key: value for key, value in values.items() if value is not None}
    if not any(key in values for key in ('temperature_c', 'humidity_percent', 'pressure_hpa')):
        return None
    values['updated'] = updated.isoformat()
    if IDX_STATION < len(tokens):
        values['station'] = tokens[IDX_STATION].replace('_', ' ')
    return values


def _series(tokens, start, count=HOUR_BLOCK):
    return [_number(token) for token in tokens[start:start + count]]


def parse_clientrawhour(text):
    """Parse clientrawhour.txt into {name: [60 values or None]}, oldest first. None if malformed."""
    tokens = (text or '').split()
    if len(tokens) < 361 or tokens[0] != '12345':
        return None
    return {name: _series(tokens, start) for name, start in HOUR_BLOCKS.items()}


def hour_trends(series, window=60):
    """Derive 1-hour change figures from parsed hour series; omit anything unmeasurable."""
    def valid(name):
        return [(i, v) for i, v in enumerate(series.get(name, [])) if v is not None]

    trends = {}
    for name, key in (('temp_c', 'temp_change_1h_c'), ('humidity', 'humidity_change_1h'), ('pressure_hpa', 'pressure_change_1h_hpa')):
        points = valid(name)
        # Need a genuine spread: samples from the first and last third of the hour.
        if len(points) >= 10 and points[0][0] < window / 3 and points[-1][0] > 2 * window / 3:
            trends[key] = _bounded(key, points[-1][1] - points[0][1])
    gusts = [v for _, v in valid('gust_kt')]
    if len(gusts) >= 10:
        trends['wind_gust_max_1h_mph'] = _bounded('wind_gust_max_1h_mph', max(gusts) * KNOTS_TO_MPH)
    return {key: value for key, value in trends.items() if value is not None}


def parse_clientrawdaily(text, today):
    """Parse clientrawdaily.txt into a list of per-day dicts, oldest first; the last day is yesterday."""
    tokens = (text or '').split()
    if len(tokens) < 130 or tokens[0] != '12345':
        return None
    days = []
    for offset in range(DAILY_DAYS):
        day = {'date': (today - timedelta(days=DAILY_DAYS - offset)).isoformat()}
        for name, start in DAILY_BLOCKS.items():
            index = start + offset
            value = _number(tokens[index]) if index < len(tokens) else None
            if value is not None:
                day[name] = value
        if len(day) > 1:
            days.append(day)
    return days or None


def parse_clientrawextra(text):
    """Parse year records (temperature and pressure extremes with dates) from clientrawextra.txt."""
    tokens = (text or '').split()
    if len(tokens) < EXTRA_YEAR_START + 36 or tokens[0] != '12345':
        return None
    records = {}
    for number, name in enumerate(EXTRA_YEAR_RECORDS):
        if name in ('wind_gust_record', 'rain_record'):
            continue
        group = tokens[EXTRA_YEAR_START + 6 * number:EXTRA_YEAR_START + 6 * number + 6]
        value = _number(group[0])
        try:
            when = datetime(int(group[5]), int(group[4]), int(group[3]), int(group[1]), int(group[2]))
        except ValueError:
            continue
        if value is not None:
            records[name] = {'value': value, 'when': when.isoformat()}
    return records or None


def sibling_url(url, name):
    """clientraw.txt -> clientrawhour.txt etc.; None if the URL doesn't end in clientraw.txt."""
    return url[:-len('clientraw.txt')] + name if url.lower().endswith('clientraw.txt') else None


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
        hour_url = sibling_url(url, 'clientrawhour.txt')
        if hour_url:
            try:
                data.update(hour_trends(parse_clientrawhour(fetch_text(hour_url)) or {}))
            except (OSError, ValueError) as error:
                log(f'hour file unavailable, publishing live data only: {error}')
        try:
            write_json_atomic(output_path, data)
        except OSError as error:
            log(f'could not write {output_path}: {error}')
            return None
        return data
    return None


def update_history(url, history_path, now=None):
    """Fetch the daily and extra files and write the history JSON. Returns the dict or None."""
    now = now or datetime.now().astimezone()
    history = {'updated': now.isoformat()}
    for name, parse, key in (('clientrawdaily.txt', lambda text: parse_clientrawdaily(text, now.date()), 'daily'),
                             ('clientrawextra.txt', parse_clientrawextra, 'year_records')):
        target = sibling_url(url, name)
        if not target:
            continue
        try:
            parsed = parse(fetch_text(target))
        except (OSError, ValueError) as error:
            log(f'{name} unavailable: {error}')
            continue
        if parsed:
            history[key] = parsed
        else:
            log(f'{name} malformed; skipped')
    if len(history) == 1:
        return None
    try:
        write_json_atomic(history_path, history)
    except OSError as error:
        log(f'could not write {history_path}: {error}')
        return None
    return history


def run_loop(url, output_path, interval, max_failures=MAX_CONSECUTIVE_FAILURES, sleep=time.sleep, history_path=None):
    """Poll forever; return 1 after max_failures consecutive failures so systemd restarts us."""
    failures = 0
    next_history = 0.0
    while True:
        if history_path and time.monotonic() >= next_history:
            next_history = time.monotonic() + HISTORY_INTERVAL_SECONDS
            update_history(url, history_path)
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
    parser.add_argument('--history-output', default=os.getenv('HWS_WEATHER_HISTORY_PATH', '/mnt/weathercam/logs/weather_station_history.json'))
    parser.add_argument('--interval', type=int, default=0, help='poll every N seconds (minimum %d); omit for a single run' % MIN_FETCH_INTERVAL_SECONDS)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    if not args.url:
        parser.error('set CLIENTRAW_URL or pass --url')
    if args.once or not args.interval:
        update_history(args.url, args.history_output)
        return 0 if update_once(args.url, args.output) else 1
    return run_loop(args.url, args.output, max(MIN_FETCH_INTERVAL_SECONDS, args.interval), history_path=args.history_output)


if __name__ == '__main__':
    sys.exit(main())
