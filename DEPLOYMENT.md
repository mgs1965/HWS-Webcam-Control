# V52.17 Deployment

V52.17 adds scene analysis, a daily keogram, weekly/monthly timelapses and an optional weather overlay while retaining the V50.3.5 runtime reliability fixes and telemetry-v4 (58-field) contract. Camera-control behavior is unchanged.

## Pre-install

```bash
python3 verify_v52_17.py
```

For a clean install, create `/etc/weathercam/dashboard.env` from `dashboard.env.example` and set `HWS_FTP_PASSWORD`. The installer supplies `weathercam.service` only when no existing unit is registered and will not overwrite an on-disk unit file.

## Install

```bash
sudo bash ./install_v52_17.sh
```

## Confirm active release

```bash
readlink -f /mnt/weathercam/app/current
systemctl is-active weathercam.service
systemctl is-active weathercam-dashboard.timer
```

Expected release: `/mnt/weathercam/app/releases/HarpendenWeatherCamera-V52.17`. The dashboard publisher is a oneshot service and may be inactive between timer runs.

## Force one publication

```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Verify the generated dashboard

```bash
grep -E 'V52.17|Recommended checks|Timelapse|Daily reliability reports|Recent captures|CPU temperature|30 days' /mnt/weathercam/dashboard/dashboard.html | head
! grep -q '__DATA__' /mnt/weathercam/dashboard/dashboard.html
```

The dashboard displays recommended checks and historical readings but does not modify camera controls or send external alerts.

## Rollback

```bash
sudo bash /mnt/weathercam/app/current/rollback_v52_17.sh
```
