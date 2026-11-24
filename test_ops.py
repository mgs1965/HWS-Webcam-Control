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


def test_release_identity():
    namespace = {}
    exec((ROOT / 'version.py').read_text(encoding='utf-8'), namespace)
    assert namespace['VERSION'] == VERSION
    assert namespace['TELEMETRY_SCHEMA_VERSION'] == 4

def test_credentials_are_not_embedded():
    core = (ROOT / 'core.py').read_text(encoding='utf-8')
    assert "FTP_PASSWORD = os.getenv('HWS_FTP_PASSWORD', '')" in core
    assert 'cGnRUCGhc' not in core

def test_camera_service_unit_and_install_preserve_existing_unit():
    service = (ROOT / 'systemd/weathercam.service').read_text(encoding='utf-8')
    installer = (ROOT / 'install.sh').read_text(encoding='utf-8')
    assert 'EnvironmentFile=/etc/weathercam/dashboard.env' in service
    assert 'Restart=on-failure' in service
    assert 'TimeoutStopSec=240' in service
    assert 'systemctl cat weathercam.service' in installer
    assert 'weathercam.service" /etc/systemd/system/weathercam.service' in installer
    assert 'refusing to overwrite it' in installer

def test_release_zip_extracts_to_matching_directory(tmp_path):
    subprocess.run(['python3', str(ROOT / 'build_release.py'), str(tmp_path)], check=True, capture_output=True)
    import zipfile
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    with zipfile.ZipFile(tmp_path / manifest['package']) as archive:
        names = archive.namelist()
    assert manifest['package'] == f'HWS-Webcam-Control-{NUM}.zip'
    assert all(name.startswith(f'HWS-Webcam-Control-{NUM}/') for name in names)
    assert f'HWS-Webcam-Control-{NUM}/manifest.json' in names
    for name in ('install.sh', 'rollback.sh', 'verify.py', 'release.py', 'update.sh', 'alerts.py'):
        assert f'HWS-Webcam-Control-{NUM}/' + name in names

def test_dashboard_modules_are_included(tmp_path):
    dashboard = load_source_module('dashboard_modules_source', ROOT / 'weathercam_dashboard/dashboard.py')
    for name in ('weather_series', 'moon_phase', 'recommended_checks', 'quality_summary', 'solar_elevation'):
        assert callable(getattr(dashboard, name))

def test_news_command_persists_and_renders_and_rejects_bad_input(tmp_path, monkeypatch):
    import pytest
    dash = _dash(tmp_path)
    monkeypatch.setattr(dash, 'OUT', tmp_path / 'out')
    dash.add_news('Station Update', 'Serviced.\nNew sensors.', '2026-11-23')
    stored = json.loads((tmp_path / 'dashboard_news.json').read_text())
    assert stored[0]['text'] == 'Serviced.\nNew sensors.'
    dash.generate(False)
    assert 'Station Update' in (dash.OUT / 'news.html').read_text()
    assert 'Station Update' in (dash.OUT / 'indexnew.html').read_text()
    with pytest.raises(ValueError, match='already exists'):
        dash.add_news('Station Update', 'Duplicate', '2026-11-23')
    with pytest.raises(ValueError):
        dash.add_news('Invalid Date', 'Text', '2026-02-30')
    assert len(dash.local_news()) == 1
    (tmp_path / 'dashboard_news.json').write_text('{broken')
    with pytest.raises(ValueError):
        dash.add_news('New Entry', 'Do not overwrite corrupt history')

def test_v54_news_today_wind_and_meteobridge_health(tmp_path):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    news = dash.news_items({'news': [{'date': '2030-11-01', 'title': 'Mine', 'text': 'x'}]})
    assert news[0]['title'] == 'Mine' and len(news) > 40 and news == sorted(news, key=lambda n: (n['date'], n['time']), reverse=True)
    daily = [{'date': '2025-11-22', 'temp_max_c': 10.0, 'temp_min_c': 3.0, 'rain_mm': 4.0}, {'date': '2024-11-22', 'temp_max_c': 12.0, 'temp_min_c': -2.0, 'rain_mm': 0.0}]
    today = dash.today_in_harpenden(now, daily)
    assert today['hottest'] == {'value': 12.0, 'year': '2024'} and today['coldest']['value'] == -2.0 and today['wettest']['year'] == '2025' and today['day_length_change_seconds'] < 0
    points = [{'wind_direction_deg': 270, 'wind_speed_mph': 12}] * 8 + [{'wind_direction_deg': 0, 'wind_speed_mph': 0.1}] * 2
    rose = dash.wind_rose_periods(now, points, [])
    assert list(rose) == ['24h'] and rose['24h']['calm_percent'] == 20.0 and rose['24h']['percent'][12][2] == 80.0
    health = dash.meteobridge_health(now, {'updated': now.isoformat(), 'bridge_data_age_s': 20}, {}, [{'date': '2026-11-21', 'rain_mm': 1.0}], {'2026-11-21': {}})
    status = {c['name']: c['status'] for c in health['checks']}
    assert status['Latest reading'] == 'ok' and status['Daily history (30 days)'] == 'bad'

def test_alerts_and_share_card(tmp_path, monkeypatch):
    dash = _dash(tmp_path)
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    alerts = dash.weather_alerts({'temperature_c': -1.0, 'wind_gust_mph': 45, 'rain_rate_mm_h': 2})
    assert [a['key'] for a in alerts] == ['frost', 'gust'] and dash.weather_alerts({'temperature_c': 5}) == []
    state = tmp_path / 'alerts.json'
    assert dash.send_alerts(alerts, now, state) == []
    sent = []
    monkeypatch.setenv('DASHBOARD_ALERT_NTFY_URL', 'http://example.invalid/topic')
    import urllib.request
    class _R:
        def close(self): pass
    monkeypatch.setattr(urllib.request, 'urlopen', lambda req, timeout=0: sent.append(req.data) or _R())
    assert dash.send_alerts(alerts, now, state) == ['frost', 'gust'] and len(sent) == 1
    assert dash.send_alerts(alerts, now + __import__('datetime').timedelta(hours=1), state) == [] and len(sent) == 1
    assert dash.send_alerts(alerts, now + __import__('datetime').timedelta(hours=7), state) == ['frost', 'gust']
    out = tmp_path / 'share.png'
    assert dash.share_card({'temperature_c': 7.5, 'wind_direction_deg': 131}, now, out) and out.read_bytes()[:4] == b'\x89PNG'

def test_alerts_report_once_repeat_and_recover():
    spec = importlib.util.spec_from_file_location('hws_alerts', ROOT / 'alerts.py')
    alerts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(alerts)
    messages, state = alerts.decide({'capture': 'old image'}, {}, 1000, 3600)
    assert messages == ['PROBLEM: old image']
    assert alerts.decide({'capture': 'old image'}, state, 1100, 3600)[0] == []
    assert alerts.decide({'capture': 'old image'}, state, 5000, 3600)[0] == ['STILL: old image']
    messages, state = alerts.decide({}, state, 5100, 3600)
    assert messages == ['RECOVERED: old image'] and state == {}

def test_news_archive_import_makes_file_authoritative(tmp_path, monkeypatch):
    monkeypatch.setenv('DASHBOARD_NEWS_PATH', str(tmp_path / 'dashboard_news.json'))
    mod = _load_dashboard(tmp_path, monkeypatch)
    mod.import_news_archive(); mod.import_news_archive()
    path = tmp_path / 'dashboard_news.json'
    entries = json.loads(path.read_text(encoding='utf-8'))
    assert len(entries) >= 40 and len(mod.news_items({})) == len(entries)
    path.write_text(json.dumps(entries[:2]), encoding='utf-8')
    assert len(mod.news_items({})) == 2

def test_health_alert_helpers(tmp_path):
    sys.path.insert(0, str(ROOT))
    import alerts
    mounts = tmp_path / 'mounts'
    mounts.write_text('/dev/root / ext4 rw 0 0\n/dev/sda1 /mnt/data ext4 ro,relatime 0 0\n', encoding='utf-8')
    assert alerts.read_only_mount('/mnt/data/logs', str(mounts)) and not alerts.read_only_mount('/home', str(mounts))
    assert alerts.throttled_flags('throttled=0x50005') == (True, True) and alerts.throttled_flags('throttled=0x0') == (False, False)
    assert alerts.throttled_flags('garbage') == (False, False)
    log = 'mmc0: error -110 whilst initialising SD card\nusb 1-1: new device\nEXT4-fs error (device mmcblk0p2): bad block'
    assert len(alerts.storage_errors(log)) == 2 and alerts.storage_errors('usb 1-1: new device') == []
    (tmp_path / 'update_failed').write_text('update to V9 failed (exit 1)', encoding='utf-8')
    assert 'V9' in alerts.marker_problem(tmp_path / 'update_failed', 'Automatic update')
    assert alerts.marker_problem(tmp_path / 'missing', 'Backup') is None

def test_backup_script_archives_logs_and_prunes(tmp_path):
    import tarfile
    logs = tmp_path / 'logs'; logs.mkdir()
    (logs / 'dashboard_news.json').write_text('[]', encoding='utf-8')
    (logs / 'big.log').write_text('x', encoding='utf-8')
    dest = tmp_path / 'offsite'
    env = {**os.environ, 'WEATHERCAM_ROOT': str(tmp_path), 'HWS_BACKUP_DEST': str(dest), 'HWS_BACKUP_KEEP': '2'}
    for _ in range(3):
        subprocess.run(['bash', str(ROOT / 'backup.sh')], env=env, check=True, capture_output=True)
        time.sleep(1.1)
    archives = sorted((tmp_path / 'backups').glob('hws-backup-*.tar.gz'))
    assert len(archives) == 2 and len(list(dest.glob('*.tar.gz'))) == 3
    names = tarfile.open(archives[-1]).getnames()
    assert any(n.endswith('dashboard_news.json') for n in names) and not any(n.endswith('.log') for n in names)
    assert not (logs / 'backup_failed').exists()


def _bash_env(tmp_path, **extra):
    return {**os.environ, 'WEATHERCAM_ROOT': str(tmp_path), **extra}


def test_backup_prunes_old_remote_copies_and_records_last_ok(tmp_path):
    (tmp_path / 'logs').mkdir()
    dest = tmp_path / 'offsite'; dest.mkdir()
    for name in ('hws-backup-20200101-000000.tar.gz', 'hws-backup-20990101-000000.tar.gz', 'mine.txt', 'hws-backup-old.tar.gz'):
        (dest / name).write_text('x', encoding='utf-8')
    env = _bash_env(tmp_path, HWS_BACKUP_DEST=str(dest), HWS_BACKUP_REMOTE_KEEP_DAYS='30')
    out = subprocess.run(['bash', str(ROOT / 'backup.sh')], env=env, check=True, capture_output=True, text=True).stdout
    left = {p.name for p in dest.iterdir()}
    assert 'hws-backup-20200101-000000.tar.gz' not in left
    assert {'hws-backup-20990101-000000.tar.gz', 'mine.txt', 'hws-backup-old.tar.gz'} <= left
    assert 'Removed old remote backup' in out
    ok = json.loads((tmp_path / 'logs' / 'backup_last_ok.json').read_text(encoding='utf-8'))
    assert ok['name'].startswith('hws-backup-') and ok['size_bytes'] > 0
    # pruning is off by default
    (dest / 'hws-backup-20200101-000000.tar.gz').write_text('x', encoding='utf-8')
    env.pop('HWS_BACKUP_REMOTE_KEEP_DAYS')
    subprocess.run(['bash', str(ROOT / 'backup.sh')], env=env, check=True, capture_output=True)
    assert (dest / 'hws-backup-20200101-000000.tar.gz').exists()


def test_restore_script_lists_restores_and_protects_env(tmp_path):
    import tarfile
    src = tmp_path / 'src'; (src / 'mnt/weathercam/logs').mkdir(parents=True); (src / 'etc/weathercam').mkdir(parents=True)
    (src / 'mnt/weathercam/logs/dashboard_news.json').write_text('[1]', encoding='utf-8')
    (src / 'etc/weathercam/dashboard.env').write_text('SECRET=1', encoding='utf-8')
    backups = tmp_path / 'backups'; backups.mkdir()
    archive = backups / 'hws-backup-20261125-080000.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(src / 'mnt', arcname='mnt'); tar.add(src / 'etc', arcname='etc')
    out = tmp_path / 'out'
    env = _bash_env(tmp_path, HWS_RESTORE_ROOT=str(out))
    run = lambda *a: subprocess.run(['bash', str(ROOT / 'restore.sh'), *a], env=env, capture_output=True, text=True)
    assert 'hws-backup-20261125-080000' in run('--list').stdout
    dry = run('--latest', '--dry-run')
    assert 'dashboard_news.json' in dry.stdout and not out.exists()
    assert run('--latest', '--yes').returncode == 0
    assert (out / 'mnt/weathercam/logs/dashboard_news.json').read_text(encoding='utf-8') == '[1]'
    assert not (out / 'etc/weathercam/dashboard.env').exists()
    assert run(str(archive), '--yes', '--with-env').returncode == 0 and (out / 'etc/weathercam/dashboard.env').exists()
    assert run(str(tmp_path / 'missing.tar.gz'), '--yes').returncode != 0


def test_weekly_digest_summarises_the_last_seven_days():
    sys.path.insert(0, str(ROOT))
    import digest
    from datetime import date
    days = {'2026-11-17': {'rain_mm': 0.0, 'temp_max_c': 9.0, 'temp_min_c': 2.0, 'wind_gust_mph': 12},
            '2026-11-18': {'rain_mm': 6.4, 'temp_max_c': 12.5, 'temp_min_c': -1.5, 'wind_gust_mph': 31},
            '2026-11-10': {'rain_mm': 99.0}}
    text = digest.build(days, date(2026, 11, 24), problems={})
    assert 'Rain: 6.4 mm' in text and 'wettest day 2026-11-18' in text and 'Warmest: 12.5 C on 2026-11-18' in text
    assert 'Coldest: -1.5 C' in text and 'Strongest gust: 31 mph' in text and '2 of 7 days' in text and '99' not in text
    assert 'No weather data' in digest.build({}, date(2026, 11, 24), problems={'x': 'Camera down'})
    assert 'Camera down' in digest.build({}, date(2026, 11, 24), problems={'x': 'Camera down'})


def test_system_status_reports_storage_and_power(monkeypatch):
    sys.path.insert(0, str(ROOT))
    import alerts
    monkeypatch.setattr(alerts, 'kernel_log', lambda: 'mmc0: error -110 timeout')
    monkeypatch.setattr(alerts, 'board_health', lambda: (True, False))
    status = alerts.system_status()
    assert status['sd_errors_1h'] == 1 and status['under_voltage'] is True
    monkeypatch.setattr(alerts, 'kernel_log', lambda: None)
    assert alerts.system_status()['sd_errors_1h'] is None
