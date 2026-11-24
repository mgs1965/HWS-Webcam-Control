#!/usr/bin/env python3
"""Send a notification when the camera, weather feed, disk or services go wrong, and when they recover.

Run every few minutes from weathercam-alerts.timer. Configure in /etc/weathercam/dashboard.env:
  HWS_ALERT_NTFY_URL   e.g. https://ntfy.sh/my-secret-topic   (push notification)
  HWS_ALERT_WEBHOOK_URL  any URL that accepts a JSON POST {"text": ...}
  HWS_ALERT_SMTP_HOST / _PORT / _USER / _PASSWORD / HWS_ALERT_EMAIL_FROM / HWS_ALERT_EMAIL_TO  (email)
Thresholds: HWS_ALERT_CAPTURE_MINUTES (10), HWS_ALERT_WEATHER_MINUTES (30), HWS_ALERT_DISK_PERCENT (90),
HWS_ALERT_REPEAT_HOURS (6), HWS_ALERT_INODE_PERCENT (90), HWS_ALERT_TEMP_C (80).
Storage and board health: read-only filesystem, inode exhaustion, SD-card/kernel I/O errors, Pi under-voltage
or throttling and CPU temperature. update.sh and backup.sh leave logs/update_failed and logs/backup_failed
markers that are reported here until the next success. State is kept in HWS_ALERT_STATE so each problem is reported once, repeated
after the repeat interval, and followed by a recovery message. Use --test to send a test message.
"""
import json
import os
import shutil
import smtplib
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(os.getenv('WEATHERCAM_ROOT', '/mnt/weathercam'))
IMAGE = Path(os.getenv('WEATHERCAM_LATEST_IMAGE', str(ROOT / 'frames/latest.jpg')))
WEATHER = Path(os.getenv('HWS_WEATHER_DATA_PATH', str(ROOT / 'logs/weather_station.json')))
STATE = Path(os.getenv('HWS_ALERT_STATE', str(ROOT / 'logs/alerts_state.json')))
LOGS = Path(os.getenv('HWS_LOG_DIR', str(ROOT / 'logs')))
SERVICES = [s for s in os.getenv('HWS_ALERT_SERVICES', 'weathercam.service').split(',') if s]


def env_number(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def file_age_minutes(path, now):
    try:
        return (now - path.stat().st_mtime) / 60
    except OSError:
        return None


def weather_age_minutes(now):
    try:
        stamp = datetime.fromisoformat(json.loads(WEATHER.read_text(encoding='utf-8'))['updated'])
        if stamp.tzinfo is None:
            stamp = stamp.astimezone()
        return (now - stamp.timestamp()) / 60
    except (OSError, ValueError, KeyError, TypeError):
        return None


def service_active(name):
    try:
        return subprocess.run(['systemctl', 'is-active', '--quiet', name], timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell (not systemd): do not raise a false alarm


def read_only_mount(path, mounts='/proc/mounts'):
    """True when the filesystem holding path is mounted read-only (typical after SD-card errors)."""
    try:
        best = ''
        flags = ''
        target = os.path.realpath(path)
        for line in Path(mounts).read_text(encoding='utf-8').splitlines():
            parts = line.split()
            if len(parts) >= 4 and (target == parts[1] or target.startswith(parts[1].rstrip('/') + '/')) and len(parts[1]) >= len(best):
                best, flags = parts[1], parts[3]
        return 'ro' in flags.split(',')
    except OSError:
        return False


def inode_percent(path):
    try:
        st = os.statvfs(path)
        return (st.f_files - st.f_ffree) * 100 / st.f_files if st.f_files else 0
    except OSError:
        return 0


def storage_errors(text):
    """Lines from the kernel log that point at a failing SD card or filesystem."""
    keys = ('mmc', 'i/o error', 'ext4-fs error', 'buffer i/o', 'blk_update_request')
    return [l for l in text.splitlines() if any(k in l.lower() for k in keys) and any(w in l.lower() for w in ('error', 'fail', 'timeout', 'crc'))]


def kernel_log():
    try:
        out = subprocess.run(['journalctl', '-k', '-p', 'err', '--since', '1 hour ago', '--no-pager', '-q'],
                             capture_output=True, text=True, timeout=20)
        return out.stdout if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def throttled_flags(raw):
    """Decode `vcgencmd get_throttled` output; returns (under_voltage_now, throttled_now)."""
    try:
        value = int(raw.strip().split('=')[-1], 16)
    except ValueError:
        return False, False
    return bool(value & 0x1), bool(value & 0x4)


def board_health():
    try:
        out = subprocess.run(['vcgencmd', 'get_throttled'], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False, False
    return throttled_flags(out)


def cpu_temp_c(path='/sys/class/thermal/thermal_zone0/temp'):
    try:
        return int(Path(path).read_text().strip()) / 1000
    except (OSError, ValueError):
        return None


def system_status():
    """Storage and power facts for the Pi health page. None means 'could not tell'."""
    log = kernel_log()
    under, throttled = board_health()
    return {
        'read_only': read_only_mount(ROOT),
        'inode_percent': round(inode_percent(ROOT), 1),
        'under_voltage': under,
        'throttled': throttled,
        'sd_errors_1h': None if log is None else len(storage_errors(log)),
        'cpu_temp_c': cpu_temp_c(),
    }


def marker_problem(path, label):
    try:
        text = path.read_text(encoding='utf-8').strip()
    except OSError:
        return None
    return '%s failed: %s' % (label, text or 'see the log')


def find_problems(now=None):
    """Return {key: message} for everything currently wrong."""
    now = now if now is not None else time.time()
    problems = {}
    limit = env_number('HWS_ALERT_CAPTURE_MINUTES', 10)
    age = file_age_minutes(IMAGE, now)
    if age is None:
        problems['capture'] = 'No camera image found at %s' % IMAGE
    elif age > limit:
        problems['capture'] = 'Camera image is %.0f minutes old (limit %.0f)' % (age, limit)
    limit = env_number('HWS_ALERT_WEATHER_MINUTES', 30)
    if WEATHER.exists() or os.getenv('HWS_ALERT_REQUIRE_WEATHER') == '1':
        age = weather_age_minutes(now)
        if age is None or age > limit:
            problems['weather'] = 'Weather data is %s (limit %.0f minutes)' % ('missing' if age is None else '%.0f minutes old' % age, limit)
    try:
        usage = shutil.disk_usage(ROOT)
        used = usage.used * 100 / usage.total
        if used > env_number('HWS_ALERT_DISK_PERCENT', 90):
            problems['disk'] = 'Disk is %.0f%% full' % used
    except OSError:
        pass
    if read_only_mount(ROOT):
        problems['readonly'] = 'Storage is mounted read-only (SD card or filesystem errors)'
    inodes = inode_percent(ROOT)
    if inodes > env_number('HWS_ALERT_INODE_PERCENT', 90):
        problems['inodes'] = 'Filesystem is %.0f%% out of inodes' % inodes
    errors = storage_errors(kernel_log() or '')
    if errors:
        problems['storage'] = 'Storage errors in the kernel log: ' + errors[-1][-160:]
    under, throttled = board_health()
    if under:
        problems['power'] = 'Pi reports under-voltage: check the power supply and cable'
    elif throttled:
        problems['throttled'] = 'Pi is throttling (too hot or low power)'
    temp = cpu_temp_c()
    if temp is not None and temp > env_number('HWS_ALERT_TEMP_C', 80):
        problems['temperature'] = 'CPU temperature is %.0f C' % temp
    for key, label in (('update', 'Automatic update'), ('backup', 'Backup')):
        found = marker_problem(LOGS / (key + '_failed'), label)
        if found:
            problems[key] = found
    for name in SERVICES:
        if not service_active(name):
            problems['service:' + name] = 'Service %s is not running' % name
    return problems


def send(text):
    sent = False
    url = os.getenv('HWS_ALERT_NTFY_URL')
    if url:
        req = urllib.request.Request(url, data=text.encode('utf-8'), headers={'Title': 'Harpenden Weather Station'})
        urllib.request.urlopen(req, timeout=20).close()
        sent = True
    url = os.getenv('HWS_ALERT_WEBHOOK_URL')
    if url:
        req = urllib.request.Request(url, data=json.dumps({'text': text}).encode('utf-8'), headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=20).close()
        sent = True
    host, to = os.getenv('HWS_ALERT_SMTP_HOST'), os.getenv('HWS_ALERT_EMAIL_TO')
    if host and to:
        msg = EmailMessage()
        msg['Subject'] = 'Harpenden Weather Station alert'
        msg['From'] = os.getenv('HWS_ALERT_EMAIL_FROM') or os.getenv('HWS_ALERT_SMTP_USER') or to
        msg['To'] = to
        msg.set_content(text)
        with smtplib.SMTP(host, int(env_number('HWS_ALERT_SMTP_PORT', 587)), timeout=30) as smtp:
            smtp.starttls()
            if os.getenv('HWS_ALERT_SMTP_USER'):
                smtp.login(os.getenv('HWS_ALERT_SMTP_USER'), os.getenv('HWS_ALERT_SMTP_PASSWORD', ''))
            smtp.send_message(msg)
        sent = True
    if not sent:
        print(text)
    return sent


def decide(problems, state, now, repeat_seconds):
    """Return (messages, new_state). Alert on new problems, repeat after the interval, announce recoveries."""
    messages, new_state = [], {}
    for key, message in problems.items():
        first = state.get(key, {}).get('first', now)
        last = state.get(key, {}).get('last_sent')
        if last is None or now - last >= repeat_seconds:
            messages.append(('PROBLEM: ' if last is None else 'STILL: ') + message)
            last = now
        new_state[key] = {'first': first, 'last_sent': last, 'message': message}
    for key, old in state.items():
        if key not in problems:
            messages.append('RECOVERED: ' + old.get('message', key))
    return messages, new_state


def main(argv):
    if '--test' in argv:
        send('Test alert from the Harpenden Weather Station')
        return 0
    now = time.time()
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    messages, new_state = decide(find_problems(now), state, now, env_number('HWS_ALERT_REPEAT_HOURS', 6) * 3600)
    if messages:
        try:
            send('\n'.join(messages))
        except Exception as exc:  # keep the state unchanged so the alert is retried next run
            print('alert delivery failed: %s' % exc, file=sys.stderr)
            return 1
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(new_state), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
