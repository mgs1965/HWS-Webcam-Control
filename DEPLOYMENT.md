# V50.1 Final Deployment

This is the V50.1 simplified-dashboard release. Camera-control logic and telemetry-v4 (58 fields) remain unchanged.

## Pre-install
```bash
python3 verify_v50_1.py
```

Configure `HWS_FTP_PASSWORD` in the weathercam service environment before installation.

## Install
```bash
sudo bash ./install_v50_1.sh
```

## Confirm active release
```bash
readlink -f /mnt/weathercam/app/current
systemctl is-active weathercam.service
systemctl is-active weathercam-dashboard.timer
```
Expected active release: `/mnt/weathercam/app/releases/HarpendenWeatherCamera-V50.1` and both services `active` (the dashboard service itself is oneshot and can be inactive between timer runs).

## Force one publication
```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Verify generated UI
```bash
grep -E 'V50.1|Looking North East|Recent events' /mnt/weathercam/dashboard/dashboard.html | head
```

## Rollback
```bash
sudo bash /mnt/weathercam/app/current/rollback_v50_1.sh
```
