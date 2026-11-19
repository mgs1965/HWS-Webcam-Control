# V49.11.2 Final Deployment

This is the frozen V49.11.2 dashboard/observability release. Camera-control logic and telemetry-v4 (58 fields) remain unchanged.

## Pre-install
```bash
python3 verify_v49_11_2.py
```

## Install
```bash
sudo ./install_v49_11_2.sh
```

## Confirm active release
```bash
readlink -f /mnt/weathercam/app/current
systemctl is-active weathercam.service
systemctl is-active weathercam-dashboard.timer
```
Expected active release: `/mnt/weathercam/app/releases/HarpendenWeatherCamera-V49.11.2` and both services `active` (the dashboard service itself is oneshot and can be inactive between timer runs).

## Force one publication
```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Verify generated UI
```bash
grep -E 'V49.11.2|Looking North East|Current Camera Settings|Recent Events|Health Checks' /mnt/weathercam/dashboard/dashboard.html | head
```

## Rollback
```bash
sudo /mnt/weathercam/app/current/rollback_v49_11_2.sh
```
