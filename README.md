# Harpenden Weather Camera V50.2

**Simplified dashboard update to V50 reliability and observability.**

V50.2 clarifies Advanced navigation and restores Raspberry Pi statistics on Live, retaining V50.1 dashboard simplification and V50 reliability work. Camera-control, exposure, mode thresholds, quality calculation, timelapse, camera FTP worker and telemetry-v4 58-field schema are retained.

## Dashboard
- Simplified Live, Trends, Events and Advanced views; the Gallery view is removed.
- Live image, overall health, camera/FTP/control status, capture/upload freshness and key camera settings.
- Trends are limited to the last 24 hours, with separate brightness, image-quality and exposure plots.
- Events provides a concise chronological incident list; Advanced clearly exposes detailed system information.
- Live restores Raspberry Pi CPU, memory, process, storage and uptime statistics.
- Gallery image publishing and exact-set FTP reconciliation continue in the background; only its dashboard view was removed.
- Missing values display as unavailable, and the camera overlay continues to show Looking North East.

## Install
```bash
unzip HWS-Webcam-Control-50.2.zip
cd HWS-Webcam-Control-50.2
python3 verify_v50_2.py
sudo bash ./install_v50_2.sh
```

## Publish immediately
```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Rollback
```bash
sudo bash /mnt/weathercam/app/current/rollback_v50_2.sh
```
