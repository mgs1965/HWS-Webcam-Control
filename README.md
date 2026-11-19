# Harpenden Weather Camera V50.1

**Simplified dashboard update to V50 reliability and observability.**

V50.1 simplifies the dashboard while retaining the V50 reliability work. Camera-control, exposure, mode thresholds, quality calculation, timelapse, camera FTP worker and telemetry-v4 58-field schema are retained.

## Dashboard
- Simplified Live, Trends, Events and Diagnostics views; the Gallery view is removed.
- Live image, overall health, camera/FTP/control status, capture/upload freshness and key camera settings.
- Trends are limited to the last 24 hours, with separate brightness, image-quality and exposure plots.
- Events provides a concise chronological incident list; Diagnostics keeps advanced system details.
- Gallery image publishing and exact-set FTP reconciliation continue in the background; only its dashboard view was removed.
- Missing values display as unavailable, and the camera overlay continues to show Looking North East.

## Install
```bash
unzip HarpendenWeatherCamera-V50.1.zip
cd HarpendenWeatherCamera-V50.1
python3 verify_v50_1.py
sudo bash ./install_v50_1.sh
```

## Publish immediately
```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Rollback
```bash
sudo bash /mnt/weathercam/app/current/rollback_v50_1.sh
```
