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
import ftplib
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
IDX_UV_INDEX, IDX_SOLAR_WM2 = 79, 127
IDX_GUST_MAX_TODAY_KT, IDX_GUST_MAX_HOUR_KT = 71, 133
IDX_LIGHTNING_TODAY, IDX_LIGHTNING_LAST_MIN, IDX_LIGHTNING_DISTANCE = 33, 114, 118

# clientraw reports rain rate per minute; the camera expects mm/h.
RAIN_RATE_TO_MM_H = 60.0

HISTORY_INTERVAL_SECONDS = 1800
SERIES_INTERVAL_SECONDS = 300
SERIES_HOURS = 24
SERIES_KEYS = ('temperature_c', 'humidity_percent', 'pressure_hpa', 'wind_speed_mph', 'wind_gust_mph', 'wind_direction_deg', 'dew_point_c', 'rain_today_mm',
               'lightning_strikes_today', 'lightning_distance', 'solar_radiation_wm2', 'uv_index')
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
    'wind_gust_max_today_mph': (0.0, 250.0),
    'lightning_strikes_last_min': (0.0, 100000.0),
    'lightning_strikes_today': (0.0, 1000000.0),
    'lightning_distance': (0.0, 1000.0),
    'heat_index_c': (-60.0, 80.0),
    'wet_bulb_c': (-60.0, 60.0),
    'wind_chill_c': (-80.0, 60.0),
    'sunshine_hours_today': (0.0, 24.0),
    'lightning_energy': (0.0, 1e12),
    'bridge_data_age_s': (0.0, 1e7),
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
        'wind_gust_max_today_mph': scaled(IDX_GUST_MAX_TODAY_KT, KNOTS_TO_MPH),
        'wind_gust_max_1h_mph': scaled(IDX_GUST_MAX_HOUR_KT, KNOTS_TO_MPH),
        'lightning_strikes_last_min': field(IDX_LIGHTNING_LAST_MIN),
        'lightning_strikes_today': field(IDX_LIGHTNING_TODAY),
        'lightning_distance': field(IDX_LIGHTNING_DISTANCE),
    }
    if raw['wind_gust_max_today_mph'] is not None and raw['wind_gust_max_1h_mph'] is not None:
        raw['wind_gust_max_today_mph'] = max(raw['wind_gust_max_today_mph'], raw['wind_gust_max_1h_mph'])
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


# Meteobridge live-data template: (output key, template expression, scale).
METEOBRIDGE_FIELDS = (
    ('temperature_c', 'th0temp-act'), ('humidity_percent', 'th0hum-act'), ('dew_point_c', 'th0dew-act'),
    ('pressure_hpa', 'thb0seapress-act'), ('wind_speed_mph', 'wind0avgwind-act=mph'), ('wind_gust_mph', 'wind0wind-act=mph'),
    ('wind_direction_deg', 'wind0dir-act'), ('wind_gust_max_today_mph', 'wind0wind-dmax=mph'),
    ('rain_rate_mm_h', 'rain0rate-act'), ('rain_today_mm', 'rain0total-daysum'),
    ('solar_radiation_wm2', 'sol0rad-act'), ('uv_index', 'uv0index-act'), ('sunshine_hours_today', 'sol0total-daysum'),
    ('lightning_strikes_today', 'lgt0total-daysum'), ('lightning_distance', 'lgt0distance-act'), ('lightning_energy', 'lgt0energy-act'),
    ('heat_index_c', 'th0heatindex-act'), ('wet_bulb_c', 'th0wetbulb-act'), ('wind_chill_c', 'wind0chill-act'),
    ('bridge_data_age_s', 'data16num-act'),
)
METEOBRIDGE_URL = None
METEOBRIDGE_USER = 'meteobridge'
METEOBRIDGE_PASSWORD = ''


def meteobridge_endpoint(base):
    """Accept 'host', 'http://host' or a full template.cgi URL and return the template.cgi URL."""
    base = (base or '').strip()
    if not base:
        return None
    if not base.lower().startswith(('http://', 'https://')):
        base = 'http://' + base
    return base if 'template.cgi' in base else base.rstrip('/') + '/cgi-bin/template.cgi'


def meteobridge_url(base, fields=None):
    from urllib.parse import quote
    template = ';'.join(f'{key}=[{expr}]' for key, expr in (fields or METEOBRIDGE_FIELDS))
    endpoint = meteobridge_endpoint(base)
    return f"{endpoint.split('?')[0]}?template={quote(template, safe='')}" if endpoint else None


def parse_meteobridge(text, now):
    """Parse the 'key=value;key=value' Meteobridge reply; missing sensors ('--', blank) are dropped."""
    allowed = {key for key, _ in METEOBRIDGE_FIELDS}
    raw = {}
    for part in (text or '').replace('\n', ';').split(';'):
        key, _, value = part.partition('=')
        key = key.strip()
        if key in allowed:
            raw[key] = _number(value.strip())
    values = {key: _bounded(key, value) for key, value in raw.items() if key in LIMITS}
    values = {key: value for key, value in values.items() if value is not None}
    if not any(key in values for key in ('temperature_c', 'humidity_percent', 'pressure_hpa')):
        return None
    values['updated'] = now.isoformat()
    values['source'] = 'meteobridge'
    return values


def _meteobridge_headers():
    if not METEOBRIDGE_PASSWORD:
        return {}
    import base64
    return {'Authorization': 'Basic ' + base64.b64encode(f'{METEOBRIDGE_USER}:{METEOBRIDGE_PASSWORD}'.encode()).decode()}


def fetch_meteobridge(base):
    url = meteobridge_url(base)
    if not url:
        return None
    try:
        return parse_meteobridge(fetch_text(url, timeout=6, headers=_meteobridge_headers()), datetime.now().astimezone())
    except (OSError, ValueError) as error:
        hint = ' (set HWS_METEOBRIDGE_USER / HWS_METEOBRIDGE_PASSWORD)' if '401' in str(error) else ''
        log(f'meteobridge unavailable{", using clientraw" if CLIENTRAW_ENABLED else ""}: {error}{hint}')
        return None


# Year-to-date extremes use aggregate suffixes that are requested separately, so an unsupported one cannot break the live reading.
YEAR_FIELDS = (('temp_max_c', 'th0temp-ymax', -60.0, 60.0), ('temp_min_c', 'th0temp-ymin', -60.0, 60.0),
               ('pressure_max_hpa', 'thb0seapress-ymax', 850.0, 1100.0), ('pressure_min_hpa', 'thb0seapress-ymin', 850.0, 1100.0))


def fetch_year_records(base):
    url = meteobridge_url(base, [(key, expr) for key, expr, _, _ in YEAR_FIELDS])
    if not url:
        return {}
    try:
        text = fetch_text(url, timeout=6, headers=_meteobridge_headers())
    except (OSError, ValueError) as error:
        log(f'meteobridge year records unavailable: {error}')
        return {}
    values = {}
    for part in text.replace('\n', ';').split(';'):
        key, _, value = part.partition('=')
        values[key.strip()] = _number(value.strip())
    records = {}
    for key, _, low, high in YEAR_FIELDS:
        value = values.get(key)
        if value is not None and low <= value <= high:
            records[key] = {'value': value, 'when': ''}
    return records


# Local history kept from the Meteobridge readings so the clientraw files can be switched off.
CLIENTRAW_ENABLED = True
MINUTE_PATH = None
DAILY_LOG_PATH = None
MINUTE_INTERVAL_SECONDS = 55
MINUTE_KEEP_MINUTES = 90
MINUTE_KEYS = ('temperature_c', 'humidity_percent', 'pressure_hpa', 'wind_speed_mph', 'wind_gust_mph', 'wind_direction_deg', 'solar_radiation_wm2')
DAILY_LOG_DAYS = 400


def _load_json(path, default):
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def record_minute(data, path=None):
    """Append a reading to the rolling minute log; returns the retained samples (oldest first)."""
    path = path or MINUTE_PATH
    if not path:
        return []
    stamp = datetime.fromisoformat(data['updated'])
    cutoff = stamp - timedelta(minutes=MINUTE_KEEP_MINUTES)
    samples = []
    for sample in _load_json(path, {}).get('samples', []):
        try:
            if isinstance(sample, dict) and datetime.fromisoformat(sample['t']) >= cutoff:
                samples.append(sample)
        except (KeyError, TypeError, ValueError):
            pass
    try:
        gap = (stamp - datetime.fromisoformat(samples[-1]['t'])).total_seconds() if samples else None
    except ValueError:
        gap = None
    if gap is None or gap >= MINUTE_INTERVAL_SECONDS or gap < 0:
        samples.append({'t': data['updated'], **{key: data.get(key) for key in MINUTE_KEYS}})
        try:
            write_json_atomic(path, {'updated': data['updated'], 'samples': samples})
        except OSError as error:
            log(f'could not write {path}: {error}')
    return samples


def local_trends(samples):
    """1-hour changes and max gust from the minute log; omitted unless the log spans at least 40 minutes."""
    points = []
    for sample in samples:
        try:
            points.append((datetime.fromisoformat(sample['t']), sample))
        except (KeyError, TypeError, ValueError):
            pass
    if len(points) < 10:
        return {}
    end = points[-1][0]
    recent = [(t, sample) for t, sample in points if (end - t).total_seconds() <= 3600]
    trends = {}
    for key, name in (('temperature_c', 'temp_change_1h_c'), ('humidity_percent', 'humidity_change_1h'), ('pressure_hpa', 'pressure_change_1h_hpa')):
        valid = [(t, sample[key]) for t, sample in recent if sample.get(key) is not None]
        if len(valid) >= 10 and (valid[-1][0] - valid[0][0]).total_seconds() >= 2400:
            trends[name] = _bounded(name, valid[-1][1] - valid[0][1])
    gusts = [sample['wind_gust_mph'] for _, sample in recent if sample.get('wind_gust_mph') is not None]
    if len(gusts) >= 10:
        trends['wind_gust_max_1h_mph'] = _bounded('wind_gust_max_1h_mph', max(gusts))
    return {key: value for key, value in trends.items() if value is not None}


def record_daily(data, path=None):
    """Track each day's temperature and pressure extremes from the readings."""
    path = path or DAILY_LOG_PATH
    if not path:
        return
    days = _load_json(path, {}).get('days')
    days = days if isinstance(days, dict) else {}
    today = days.setdefault(str(data['updated'])[:10], {})
    before = dict(today)
    temperature, pressure = data.get('temperature_c'), data.get('pressure_hpa')
    if temperature is not None:
        today['temp_max_c'] = max(today.get('temp_max_c', temperature), temperature)
        today['temp_min_c'] = min(today.get('temp_min_c', temperature), temperature)
    if pressure is not None:
        today['pressure_min_hpa'] = min(today.get('pressure_min_hpa', pressure), pressure)
    if today != before or len(days) > DAILY_LOG_DAYS:
        days = {day: days[day] for day in sorted(days)[-DAILY_LOG_DAYS:]}
        try:
            write_json_atomic(path, {'days': days})
        except OSError as error:
            log(f'could not write {path}: {error}')


def update_history_local(history_path, now=None):
    """Write the history JSON from the local daily log (used when the clientraw files are off)."""
    now = now or datetime.now().astimezone()
    days = _load_json(DAILY_LOG_PATH, {}).get('days') if DAILY_LOG_PATH else None
    days = days if isinstance(days, dict) else {}
    first = (now.date() - timedelta(days=DAILY_DAYS)).isoformat()
    merged = {}
    previous = _load_json(history_path, {}).get('daily')
    for entry in previous if isinstance(previous, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get('date'), str):
            merged[entry['date']] = entry
    for day, values in days.items():
        if isinstance(values, dict):
            merged[day] = {'date': day, **values}
    daily = [merged[day] for day in sorted(merged) if first <= day < now.date().isoformat()]
    history = {'updated': now.isoformat()}
    if daily:
        history['daily'] = daily
    records = fetch_year_records(METEOBRIDGE_URL) if METEOBRIDGE_URL else {}
    if records:
        history['year_records'] = records
    if len(history) == 1:
        return None
    try:
        write_json_atomic(history_path, history)
    except OSError as error:
        log(f'could not write {history_path}: {error}')
        return None
    return history


LIVE_PATH = None
LIVE_UPLOAD_SECONDS = 120
LIVE_RETRY_SECONDS = 300
LIVE_KEYS = ('updated', 'source', 'temperature_c', 'humidity_percent', 'pressure_hpa', 'wind_speed_mph', 'wind_gust_mph', 'wind_direction_deg', 'dew_point_c',
             'rain_rate_mm_h', 'rain_today_mm', 'solar_radiation_wm2', 'uv_index', 'heat_index_c', 'wet_bulb_c', 'wind_chill_c', 'lightning_strikes_today',
             'lightning_distance', 'bridge_data_age_s', 'temp_change_1h_c', 'humidity_change_1h', 'pressure_change_1h_hpa', 'wind_gust_max_1h_mph')
_live_state = {'next': 0.0}


def upload_live(path, name='weather-live.json'):
    """Upload the live file to the dashboard FTP folder; a temporary name is renamed so readers never see a partial file."""
    host, user, password = os.getenv('DASHBOARD_FTP_HOST'), os.getenv('DASHBOARD_FTP_USER'), os.getenv('DASHBOARD_FTP_PASSWORD')
    if not (host and user and password):
        return None
    ftp = (ftplib.FTP_TLS if os.getenv('DASHBOARD_FTP_TLS', '0') != '0' else ftplib.FTP)()
    try:
        ftp.connect(host, int(os.getenv('DASHBOARD_FTP_PORT', '21')), timeout=15)
        ftp.login(user, password)
        if isinstance(ftp, ftplib.FTP_TLS):
            ftp.prot_p()
        ftp.cwd(os.getenv('DASHBOARD_FTP_DIR', '/'))
        with open(path, 'rb') as handle:
            ftp.storbinary('STOR ' + name + '.uploading', handle)
        try:
            ftp.delete(name)
        except ftplib.error_perm:
            pass
        ftp.rename(name + '.uploading', name)
        ftp.quit()
        return True
    except (OSError, ftplib.Error, ValueError) as error:
        log(f'live upload failed: {error}')
        return False
    finally:
        try:
            ftp.close()
        except OSError:
            pass


def publish_live(data, clock=time.monotonic):
    """Write the small live file and, at most every LIVE_UPLOAD_SECONDS, upload it for the dashboard's live updates."""
    if not LIVE_PATH or not data:
        return False
    try:
        write_json_atomic(LIVE_PATH, {key: data[key] for key in LIVE_KEYS if data.get(key) is not None})
    except OSError as error:
        log(f'could not write {LIVE_PATH}: {error}')
        return False
    if LIVE_UPLOAD_SECONDS <= 0 or clock() < _live_state['next']:
        return True
    ok = upload_live(LIVE_PATH)
    if ok is None:
        _live_state['next'] = clock() + 3600
    else:
        _live_state['next'] = clock() + (LIVE_UPLOAD_SECONDS if ok else max(LIVE_UPLOAD_SECONDS, LIVE_RETRY_SECONDS))
    return True


def diagnose(base):
    """Print the raw Meteobridge reply next to the converted values, for checking units against the console."""
    url = meteobridge_url(base)
    if not url:
        print('no Meteobridge URL')
        return 1
    try:
        text = fetch_text(url, timeout=10, headers=_meteobridge_headers())
    except (OSError, ValueError) as error:
        print(f'Meteobridge unavailable: {error}')
        return 1
    raw = dict(part.partition('=')[::2] for part in text.replace('\n', ';').split(';') if '=' in part)
    data = parse_meteobridge(text, datetime.now().astimezone()) or {}
    print(f"{'field':26} {'raw reply':>12}  {'converted value':>16}")
    for key, expr in METEOBRIDGE_FIELDS:
        print(f"{key:26} {raw.get(key, '-').strip():>12}  {data.get(key, '-')!s:>16}  [{expr}]")
    print('Compare these with the console. Units: wind mph, rain mm, pressure hPa, temperature C.')
    return 0


def sibling_url(url, name):
    """clientraw.txt -> clientrawhour.txt etc.; None if the URL doesn't end in clientraw.txt."""
    return url[:-len('clientraw.txt')] + name if url.lower().endswith('clientraw.txt') else None


def fetch_text(url, timeout=10, headers=None):
    if not url.lower().startswith(('http://', 'https://')):
        raise ValueError('CLIENTRAW_URL must be http(s)')
    request = urllib.request.Request(url, headers={'User-Agent': 'HWS-Webcam-Control weather_station/1', **(headers or {})})
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


RAW_PATH = None
COMPARE_PATH = None
RAW_FILES = {}


def record_raw(name, text):
    """Keep the raw tokens of a clientraw file (header 12345 only) for the dashboard's data tab."""
    tokens = text.split()
    if len(tokens) > 1 and tokens[0] == '12345':
        RAW_FILES[name] = {'fetched': datetime.now().astimezone().isoformat(timespec='seconds'), 'tokens': tokens[1:]}


def flush_raw():
    if RAW_PATH and RAW_FILES:
        try:
            write_json_atomic(RAW_PATH, RAW_FILES)
        except OSError as error:
            log(f'could not write {RAW_PATH}: {error}')


FETCH_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
MAX_CONSECUTIVE_FAILURES = 10


def log(message):
    print(f'[WEATHER STATION] {message}', file=sys.stderr, flush=True)


def append_series(path, data):
    """Add a sample to the rolling 24-hour series file, at most one per SERIES_INTERVAL_SECONDS."""
    try:
        stamp = datetime.fromisoformat(data['updated'])
        with open(path, encoding='utf-8') as handle:
            samples = json.load(handle).get('samples', [])
    except FileNotFoundError:
        samples = []
    except (OSError, ValueError, KeyError, AttributeError):
        samples = []
    samples = [s for s in samples if isinstance(s, dict) and isinstance(s.get('t'), str)]
    try:
        last = datetime.fromisoformat(samples[-1]['t']) if samples else None
    except ValueError:
        last, samples = None, []
    if last and 0 <= (stamp - last).total_seconds() < SERIES_INTERVAL_SECONDS:
        return False
    cutoff = stamp - timedelta(hours=SERIES_HOURS)
    kept = []
    for sample in samples:
        try:
            if datetime.fromisoformat(sample['t']) >= cutoff:
                kept.append(sample)
        except ValueError:
            pass
    kept.append({'t': data['updated'], **{key: data.get(key) for key in SERIES_KEYS}})
    write_json_atomic(path, {'updated': data['updated'], 'samples': kept})
    return True


def update_once(url, output_path, attempts=FETCH_ATTEMPTS, retry_delay=RETRY_DELAY_SECONDS, sleep=time.sleep, series_path=None):
    """Fetch and publish once, then push the small live file for the dashboard."""
    data = _update_once(url, output_path, attempts, retry_delay, sleep, series_path)
    if data:
        publish_live(data)
    return data


def _update_once(url, output_path, attempts, retry_delay, sleep, series_path):
    """Fetch, parse and publish once, retrying transient network errors.

    Returns the dict written, or None. Stale or malformed files are not
    retried (the station itself has to recover) and are never written.
    """
    live = fetch_meteobridge(METEOBRIDGE_URL) if METEOBRIDGE_URL else None
    if live:
        samples = record_minute(live)
        record_daily(live)
        if not CLIENTRAW_ENABLED:
            live.update(local_trends(samples))
    if not CLIENTRAW_ENABLED:
        if live is None:
            log('meteobridge reading unavailable; not publishing (clientraw is switched off)')
            return None
        try:
            write_json_atomic(output_path, live)
        except OSError as error:
            log(f'could not write {output_path}: {error}')
            return None
        if series_path:
            try:
                append_series(series_path, live)
            except OSError as error:
                log(f'could not write {series_path}: {error}')
        return live
    for attempt in range(1, attempts + 1):
        try:
            text = fetch_text(url)
        except (OSError, ValueError) as error:
            log(f'fetch failed (attempt {attempt}/{attempts}): {error}')
            if live is None and attempt < attempts:
                sleep(retry_delay * attempt)
            if live is None:
                continue
            text = ''
        data = parse_clientraw(text, datetime.now().astimezone()) if text else None
        if data is None and live is None:
            log('clientraw malformed or stale; not publishing')
            return None
        if text and data is not None:
            record_raw('clientraw', text)
        if data and live and COMPARE_PATH:
            try:
                write_json_atomic(COMPARE_PATH, {'updated': live['updated'], 'clientraw': data, 'meteobridge': live})
            except OSError as error:
                log(f'could not write {COMPARE_PATH}: {error}')
        data = {**(data or {}), **(live or {})}
        hour_url = sibling_url(url, 'clientrawhour.txt')
        if hour_url:
            try:
                hour_text = fetch_text(hour_url)
                record_raw('clientrawhour', hour_text)
                data.update(hour_trends(parse_clientrawhour(hour_text) or {}))
            except (OSError, ValueError) as error:
                log(f'hour file unavailable, publishing live data only: {error}')
        try:
            write_json_atomic(output_path, data)
        except OSError as error:
            log(f'could not write {output_path}: {error}')
            return None
        flush_raw()
        if series_path:
            try:
                append_series(series_path, data)
            except OSError as error:
                log(f'could not write {series_path}: {error}')
        return data
    return None


def seed_local_history(url, now=None):
    """Back-fill the local minute and daily logs from the clientraw hour/daily files without overwriting real readings."""
    now = now or datetime.now().astimezone()
    added = {'minutes': 0, 'days': 0}
    try:
        hour = parse_clientrawhour(fetch_text(sibling_url(url, 'clientrawhour.txt')))
    except (OSError, ValueError, TypeError) as error:
        log(f'history seed: clientrawhour.txt unavailable: {error}')
        hour = None
    if hour and MINUTE_PATH:
        samples = [x for x in _load_json(MINUTE_PATH, {}).get('samples', []) if isinstance(x, dict) and 't' in x]
        try:
            first = min(datetime.fromisoformat(x['t']) for x in samples) if samples else now
        except ValueError:
            first = now
        convert = (('wind_speed_mph', 'wind_kt', KNOTS_TO_MPH), ('wind_gust_mph', 'gust_kt', KNOTS_TO_MPH), ('wind_direction_deg', 'wind_dir', 1.0),
                   ('temperature_c', 'temp_c', 1.0), ('humidity_percent', 'humidity', 1.0), ('pressure_hpa', 'pressure_hpa', 1.0))
        seeded = []
        for index in range(HOUR_BLOCK):
            stamp = now.replace(second=0, microsecond=0) - timedelta(minutes=HOUR_BLOCK - 1 - index)
            if stamp >= first - timedelta(seconds=MINUTE_INTERVAL_SECONDS):
                continue
            sample = {'t': stamp.isoformat(timespec='seconds'), **{key: None for key in MINUTE_KEYS}}
            for key, source, scale in convert:
                value = hour[source][index]
                sample[key] = _bounded(key, value * scale) if value is not None else None
            if any(sample[key] is not None for key, _, _ in convert):
                seeded.append(sample)
        if seeded:
            stamp = max(datetime.fromisoformat(x['t']) for x in seeded + samples)
            samples = sorted(seeded + samples, key=lambda x: x['t'])
            try:
                write_json_atomic(MINUTE_PATH, {'updated': stamp.isoformat(), 'samples': samples})
                added['minutes'] = len(seeded)
            except OSError as error:
                log(f'could not write {MINUTE_PATH}: {error}')
    try:
        daily = parse_clientrawdaily(fetch_text(sibling_url(url, 'clientrawdaily.txt')), now.date())
    except (OSError, ValueError, TypeError) as error:
        log(f'history seed: clientrawdaily.txt unavailable: {error}')
        daily = None
    if daily and DAILY_LOG_PATH:
        days = _load_json(DAILY_LOG_PATH, {}).get('days')
        days = days if isinstance(days, dict) else {}
        for entry in daily:
            if entry['date'] not in days:
                days[entry['date']] = {key: value for key, value in entry.items() if key != 'date'}
                added['days'] += 1
        if added['days']:
            days = {day: days[day] for day in sorted(days)[-DAILY_LOG_DAYS:]}
            try:
                write_json_atomic(DAILY_LOG_PATH, {'days': days})
            except OSError as error:
                log(f'could not write {DAILY_LOG_PATH}: {error}')
                added['days'] = 0
    if added['minutes'] or added['days']:
        log(f"history seed from clientraw: {added['minutes']} minutes, {added['days']} days")
    return added


def update_history(url, history_path, now=None):
    """Fetch the daily and extra files and write the history JSON. Returns the dict or None."""
    now = now or datetime.now().astimezone()
    if not CLIENTRAW_ENABLED:
        return update_history_local(history_path, now)
    history = {'updated': now.isoformat()}
    for name, parse, key in (('clientrawdaily.txt', lambda text: parse_clientrawdaily(text, now.date()), 'daily'),
                             ('clientrawextra.txt', parse_clientrawextra, 'year_records')):
        target = sibling_url(url, name)
        if not target:
            continue
        try:
            body = fetch_text(target)
            parsed = parse(body)
        except (OSError, ValueError) as error:
            log(f'{name} unavailable: {error}')
            continue
        record_raw(name[:-4], body)
        if parsed:
            history[key] = parsed
        else:
            log(f'{name} malformed; skipped')
    flush_raw()
    if len(history) == 1:
        return None
    try:
        write_json_atomic(history_path, history)
    except OSError as error:
        log(f'could not write {history_path}: {error}')
        return None
    return history


def run_loop(url, output_path, interval, max_failures=MAX_CONSECUTIVE_FAILURES, sleep=time.sleep, history_path=None, series_path=None):
    """Poll forever; return 1 after max_failures consecutive failures so systemd restarts us."""
    failures = 0
    next_history = 0.0
    while True:
        if history_path and time.monotonic() >= next_history:
            next_history = time.monotonic() + HISTORY_INTERVAL_SECONDS
            update_history(url, history_path)
        if update_once(url, output_path, series_path=series_path):
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
    parser.add_argument('--series-output', default=os.getenv('HWS_WEATHER_SERIES_PATH', '/mnt/weathercam/logs/weather_station_series.json'))
    parser.add_argument('--raw-output', default=os.getenv('HWS_WEATHER_RAW_PATH', '/mnt/weathercam/logs/weather_station_raw.json'))
    parser.add_argument('--compare-output', default=os.getenv('HWS_WEATHER_COMPARE_PATH', '/mnt/weathercam/logs/weather_station_compare.json'))
    parser.add_argument('--minute-output', default=os.getenv('HWS_WEATHER_MINUTE_PATH', '/mnt/weathercam/logs/weather_station_minute.json'))
    parser.add_argument('--daily-log-output', default=os.getenv('HWS_WEATHER_DAILY_LOG_PATH', '/mnt/weathercam/logs/weather_station_daily_log.json'))
    parser.add_argument('--no-clientraw', action='store_true', default=os.getenv('HWS_CLIENTRAW_ENABLED', '1').strip().lower() in ('0', 'false', 'no', 'off'), help='use only the Meteobridge; the clientraw files are not fetched')
    parser.add_argument('--meteobridge', default=os.getenv('HWS_METEOBRIDGE_URL', ''), help='Meteobridge host or template.cgi URL; read first, clientraw is the fallback')
    parser.add_argument('--meteobridge-user', default=os.getenv('HWS_METEOBRIDGE_USER', 'meteobridge'))
    parser.add_argument('--meteobridge-password', default=os.getenv('HWS_METEOBRIDGE_PASSWORD', ''))
    parser.add_argument('--live-output', default=os.getenv('HWS_WEATHER_LIVE_PATH', '/mnt/weathercam/logs/weather_live.json'))
    parser.add_argument('--live-upload-seconds', type=int, default=int(os.getenv('HWS_LIVE_UPLOAD_SECONDS', '120') or 0), help='upload the small live file for the dashboard every N seconds (0 = never)')
    parser.add_argument('--diagnose', action='store_true', help='print the Meteobridge values for checking units against the console, then exit')
    parser.add_argument('--interval', type=int, default=0, help='poll every N seconds (minimum %d); omit for a single run' % MIN_FETCH_INTERVAL_SECONDS)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    if args.no_clientraw and not args.meteobridge:
        parser.error('HWS_CLIENTRAW_ENABLED=0 needs HWS_METEOBRIDGE_URL')
    if not args.url and not args.meteobridge:
        parser.error('set CLIENTRAW_URL (or HWS_METEOBRIDGE_URL) or pass --url')
    seed_url = args.url
    args.url = args.url or 'http://invalid.invalid/clientraw.txt'
    global RAW_PATH, COMPARE_PATH, LIVE_PATH, LIVE_UPLOAD_SECONDS, MINUTE_PATH, DAILY_LOG_PATH, CLIENTRAW_ENABLED, METEOBRIDGE_URL, METEOBRIDGE_USER, METEOBRIDGE_PASSWORD
    METEOBRIDGE_USER, METEOBRIDGE_PASSWORD = args.meteobridge_user, args.meteobridge_password
    RAW_PATH = args.raw_output
    LIVE_PATH, LIVE_UPLOAD_SECONDS = args.live_output, args.live_upload_seconds
    COMPARE_PATH = args.compare_output
    MINUTE_PATH, DAILY_LOG_PATH, CLIENTRAW_ENABLED = args.minute_output, args.daily_log_output, not args.no_clientraw
    METEOBRIDGE_URL = args.meteobridge or None
    if args.diagnose:
        return diagnose(args.meteobridge)
    if seed_url and METEOBRIDGE_URL:
        seed_local_history(seed_url)
    if args.once or not args.interval:
        update_history(args.url, args.history_output)
        return 0 if update_once(args.url, args.output, series_path=args.series_output) else 1
    return run_loop(args.url, args.output, max(MIN_FETCH_INTERVAL_SECONDS, args.interval), history_path=args.history_output, series_path=args.series_output)


if __name__ == '__main__':
    sys.exit(main())
