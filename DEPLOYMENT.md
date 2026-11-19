# V50.3.5 Final Deployment

This release includes runtime recovery, Pi health decoding, daily report and clean-install service fixes. Camera-control behavior and telemetry-v4 (58 fields) remain unchanged.

## Pre-install
```bash
python3 verify_v50_3_5.py
```

For a clean install, create `/etc/weathercam/dashboard.env` from `dashboard.env.example` and set `HWS_FTP_PASSWORD`. The installer supplies `weathercam.service` only when no camera service unit already exists.

## Install
```bash
sudo bash ./install_v50_3_5.sh
```

## Confirm active release
```bash
readlink -f /mnt/weathercam/app/current
systemctl is-active weathercam.service
systemctl is-active weathercam-dashboard.timer
```
Expected active release: `/mnt/weathercam/app/releases/HarpendenWeatherCamera-V50.3.5` and both services `active` (the dashboard service itself is oneshot and can be inactive between timer runs).

## Force one publication
```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Verify generated UI
```bash
grep -E 'V50.3.5|Looking North East|Recent events|Raspberry Pi status|Advanced|30 days|Camera process memory|Camera mode performance' /mnt/weathercam/dashboard/dashboard.html | head
! grep -q '__DATA__' /mnt/weathercam/dashboard/dashboard.html
```

## Rollback
```bash
sudo bash /mnt/weathercam/app/current/rollback_v50_3_5.sh
```
