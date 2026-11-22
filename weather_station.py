#!/usr/bin/env python3
"""Meteobridge weather-station fetcher.

Standalone producer for the JSON file the camera already consumes
(HWS_WEATHER_DATA_PATH, default /mnt/weathercam/logs/weather_station.json),
read from a Meteobridge (HWS_METEOBRIDGE_URL), plus a history file
(HWS_WEATHER_HISTORY_PATH) built from the local daily log and the Meteobridge
year records. It never touches camera control. Missing or malformed data is
never written, so the camera simply treats the station as unavailable.

Usage:
    HWS_METEOBRIDGE_URL=192.168.0.65 python3 weather_station.py --once
    HWS_METEOBRIDGE_URL=... python3 weather_station.py --interval 30
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

MIN_FETCH_INTERVAL_SECONDS = 30
MAX_BYTES = 65536

HISTORY_INTERVAL_SECONDS = 1800
SERIES_INTERVAL_SECONDS = 300
SERIES_HOURS = 24
SERIES_KEYS = ('temperature_c', 'humidity_percent', 'pressure_hpa', 'wind_speed_mph', 'wind_gust_mph', 'wind_direction_deg', 'dew_point_c', 'rain_today_mm',
               'lightning_strikes_today', 'lightning_distance', 'solar_radiation_wm2', 'uv_index')
DAILY_DAYS = 30

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


# Meteobridge live-data template: (output key, template expression, scale).
METEOBRIDGE_FIELDS = (
    ('temperature_c', 'th0temp-act'), ('humidity_percent', 'th0hum-act'), ('dew_point_c', 'th0dew-act'),
    ('pressure_hpa', 'thb0seapress-act'), ('wind_speed_mph', 'wind0avgwind-act=mph'), ('wind_gust_mph', 'wind0wind-act=mph'),
    ('wind_direction_deg', 'wind0dir-act'), ('wind_gust_max_today_mph', 'wind0wind-dmax=mph'),
    ('rain_rate_mm_h', 'rain0rate-act'), ('rain_today_mm', 'rain0total-sum@D0'),
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
    if raw.get('sunshine_hours_today') is not None and raw['sunshine_hours_today'] > 24:
        raw['sunshine_hours_today'] /= 60.0  # Meteobridge reports sunshine in minutes
    values = {key: _bounded(key, value) for key, value in raw.items() if key in LIMITS}
    values = {key: value for key, value in values.items() if value is not None}
    if not any(key in values for key in ('temperature_c', 'humidity_percent', 'pressure_hpa')):
        return None
    values['updated'] = now.isoformat()
    values['source'] = 'meteobridge'
    return values


def _meteobridge_headers():
    password = METEOBRIDGE_PASSWORD or os.getenv('HWS_METEOBRIDGE_PASSWORD', '')
    if not password:
        return {}
    import base64
    user = METEOBRIDGE_USER if METEOBRIDGE_PASSWORD else os.getenv('HWS_METEOBRIDGE_USER', METEOBRIDGE_USER)
    return {'Authorization': 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()}


def fetch_meteobridge(base):
    url = meteobridge_url(base)
    if not url:
        return None
    try:
        return parse_meteobridge(fetch_text(url, timeout=6, headers=_meteobridge_headers()), datetime.now().astimezone())
    except (OSError, ValueError) as error:
        hint = ' (set HWS_METEOBRIDGE_USER / HWS_METEOBRIDGE_PASSWORD)' if '401' in str(error) else ''
        log(f'meteobridge unavailable: {error}{hint}')
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


# Local history kept from the Meteobridge readings.
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
    rain = data.get('rain_today_mm')
    if rain is not None:
        today['rain_mm'] = max(today.get('rain_mm', rain), rain)
    if pressure is not None:
        today['pressure_min_hpa'] = min(today.get('pressure_min_hpa', pressure), pressure)
    if today != before or len(days) > DAILY_LOG_DAYS:
        days = {day: days[day] for day in sorted(days)[-DAILY_LOG_DAYS:]}
        try:
            write_json_atomic(path, {'days': days})
        except OSError as error:
            log(f'could not write {path}: {error}')


def update_history(history_path, now=None):
    """Write the history JSON from the local daily log and the Meteobridge year records."""
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
LIVE_UPLOAD_SECONDS = 30
LIVE_RETRY_SECONDS = 300
LIVE_KEYS = ('updated', 'source', 'temperature_c', 'humidity_percent', 'pressure_hpa', 'wind_speed_mph', 'wind_gust_mph', 'wind_direction_deg', 'dew_point_c',
             'rain_rate_mm_h', 'rain_today_mm', 'solar_radiation_wm2', 'uv_index', 'heat_index_c', 'wet_bulb_c', 'wind_chill_c', 'lightning_strikes_today',
             'lightning_distance', 'bridge_data_age_s', 'temp_change_1h_c', 'humidity_change_1h', 'pressure_change_1h_hpa', 'wind_gust_max_1h_mph', 'wind_gust_max_today_mph', 'sunshine_hours_today', 'lightning_energy')
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


BACKFILL_FIELDS = (('temp_max_c', 'th0temp-max', -60.0, 60.0), ('temp_min_c', 'th0temp-min', -60.0, 60.0), ('humidity_avg', 'th0hum-avg', 0.0, 100.0),
                   ('rain_mm', 'rain0total-sum', 0.0, 1000.0), ('pressure_max_hpa', 'thb0seapress-max', 850.0, 1100.0), ('pressure_min_hpa', 'thb0seapress-min', 850.0, 1100.0),
                   ('wind_gust_mph', 'wind0wind-max=mph', 0.0, 200.0))
BACKFILL_ARCHIVE_NAME = 'weather_station_archive.json'


def backfill_expressions(offset):
    """Meteobridge template expressions for the day `offset` days ago ('@D<n>' goes before any '=unit')."""
    out = []
    for key, expr, _, _ in BACKFILL_FIELDS:
        base, eq, unit = expr.partition('=')
        out.append((key, f'{base}@D{offset}{eq}{unit}'))
    return out


def parse_backfill_day(text):
    limits = {key: (low, high) for key, _, low, high in BACKFILL_FIELDS}
    out = {}
    for part in (text or '').replace('\n', ';').split(';'):
        key, _, value = part.partition('=')
        key = key.strip()
        number = _number(value.strip()) if key in limits else None
        if number is not None and limits[key][0] <= number <= limits[key][1]:
            out[key] = round(number, 2)
    return out


def backfill_archive(base, path, days=4000, today=None, fetch=None, sleep=time.sleep, max_empty=45):
    """One-off import of old daily values from the Meteobridge database into an archive file; stops after a long run of empty days."""
    fetch = fetch or (lambda url: fetch_text(url, timeout=10, headers=_meteobridge_headers()))
    today = today or datetime.now().astimezone().date()
    archive = _load_json(path, {}).get('days')
    archive = archive if isinstance(archive, dict) else {}
    added = empty = 0
    for offset in range(1, days + 1):
        day = (today - timedelta(days=offset)).isoformat()
        if day in archive and archive[day] and 'rain_mm' in archive[day]:
            empty = 0
            continue
        url = meteobridge_url(base, backfill_expressions(offset))
        try:
            values = parse_backfill_day(fetch(url))
        except (OSError, ValueError) as error:
            log(f'backfill stopped at {day}: {error}')
            break
        if values.get('temp_max_c') is None and values.get('temp_min_c') is None:
            empty += 1
            if empty >= max_empty:
                break
            continue
        empty = 0
        archive[day] = {**archive.get(day, {}), **values}
        added += 1
        if added % 50 == 0:
            write_json_atomic(path, {'days': dict(sorted(archive.items()))})
            print(f'  ... {added} days (back to {day})', flush=True)
        sleep(0.05)
    if added:
        write_json_atomic(path, {'days': dict(sorted(archive.items()))})
    return {'added': added, 'total': len(archive), 'first': min(archive) if archive else None}


def fetch_text(url, timeout=10, headers=None):
    if not url.lower().startswith(('http://', 'https://')):
        raise ValueError('URL must be http(s)')
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


def update_once(output_path, series_path=None):
    """Read the Meteobridge, publish the reading, then push the small live file for the dashboard."""
    data = _update_once(output_path, series_path)
    if data:
        publish_live(data)
    return data


def _update_once(output_path, series_path):
    live = fetch_meteobridge(METEOBRIDGE_URL)
    if live is None:
        log('meteobridge reading unavailable; not publishing')
        return None
    samples = record_minute(live)
    record_daily(live)
    live.update(local_trends(samples))
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


def run_loop(output_path, interval, max_failures=MAX_CONSECUTIVE_FAILURES, sleep=time.sleep, history_path=None, series_path=None):
    """Poll forever; return 1 after max_failures consecutive failures so systemd restarts us."""
    failures = 0
    next_history = 0.0
    while True:
        if history_path and time.monotonic() >= next_history:
            next_history = time.monotonic() + HISTORY_INTERVAL_SECONDS
            update_history(history_path)
        if update_once(output_path, series_path=series_path):
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
    parser.add_argument('--output', default=os.getenv('HWS_WEATHER_DATA_PATH', '/mnt/weathercam/logs/weather_station.json'))
    parser.add_argument('--history-output', default=os.getenv('HWS_WEATHER_HISTORY_PATH', '/mnt/weathercam/logs/weather_station_history.json'))
    parser.add_argument('--series-output', default=os.getenv('HWS_WEATHER_SERIES_PATH', '/mnt/weathercam/logs/weather_station_series.json'))
    parser.add_argument('--minute-output', default=os.getenv('HWS_WEATHER_MINUTE_PATH', '/mnt/weathercam/logs/weather_station_minute.json'))
    parser.add_argument('--daily-log-output', default=os.getenv('HWS_WEATHER_DAILY_LOG_PATH', '/mnt/weathercam/logs/weather_station_daily_log.json'))
    parser.add_argument('--meteobridge', default=os.getenv('HWS_METEOBRIDGE_URL', ''), help='Meteobridge host or template.cgi URL (required)')
    parser.add_argument('--meteobridge-user', default=os.getenv('HWS_METEOBRIDGE_USER', 'meteobridge'))
    parser.add_argument('--meteobridge-password', default=os.getenv('HWS_METEOBRIDGE_PASSWORD', ''))
    parser.add_argument('--live-output', default=os.getenv('HWS_WEATHER_LIVE_PATH', '/mnt/weathercam/logs/weather_live.json'))
    parser.add_argument('--live-upload-seconds', type=int, default=int(os.getenv('HWS_LIVE_UPLOAD_SECONDS', '30') or 0), help='upload the small live file for the dashboard every N seconds (0 = never)')
    parser.add_argument('--diagnose', action='store_true', help='print the Meteobridge values for checking units against the console, then exit')
    parser.add_argument('--backfill', type=int, nargs='?', const=4000, default=0, metavar='DAYS', help='import up to DAYS (default 4000) of old daily values from the Meteobridge database into the archive file, then exit')
    parser.add_argument('--archive-output', default=os.getenv('HWS_WEATHER_ARCHIVE_PATH', '/mnt/weathercam/logs/' + BACKFILL_ARCHIVE_NAME))
    parser.add_argument('--interval', type=int, default=0, help='poll every N seconds (minimum %d); omit for a single run' % MIN_FETCH_INTERVAL_SECONDS)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    if not args.meteobridge:
        parser.error('set HWS_METEOBRIDGE_URL or pass --meteobridge')
    global LIVE_PATH, LIVE_UPLOAD_SECONDS, MINUTE_PATH, DAILY_LOG_PATH, METEOBRIDGE_URL, METEOBRIDGE_USER, METEOBRIDGE_PASSWORD
    METEOBRIDGE_USER, METEOBRIDGE_PASSWORD = args.meteobridge_user, args.meteobridge_password
    LIVE_PATH, LIVE_UPLOAD_SECONDS = args.live_output, args.live_upload_seconds
    MINUTE_PATH, DAILY_LOG_PATH = args.minute_output, args.daily_log_output
    METEOBRIDGE_URL = args.meteobridge or None
    if args.diagnose:
        return diagnose(args.meteobridge)
    if args.backfill:
        if not args.meteobridge:
            parser.error('--backfill needs HWS_METEOBRIDGE_URL')
        result = backfill_archive(args.meteobridge, args.archive_output, args.backfill)
        print(f"Backfill complete: {result['added']} new days, {result['total']} in archive (earliest {result['first']}) -> {args.archive_output}")
        return 0 if result['total'] else 1
    if args.once or not args.interval:
        update_history(args.history_output)
        return 0 if update_once(args.output, series_path=args.series_output) else 1
    return run_loop(args.output, max(MIN_FETCH_INTERVAL_SECONDS, args.interval), history_path=args.history_output, series_path=args.series_output)


if __name__ == '__main__':
    sys.exit(main())
