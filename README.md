# Harpenden Weather Camera V50.3.3

**Simplified dashboard update to V50 reliability and observability.**

V50.3.3 fixes the main-view radio/CSS selector placement so the dashboard renders its selected view. It retains JavaScript-enhanced navigation, V50.3.1 template-data handling and V50.3 trend improvements. Camera-control, exposure, mode thresholds, quality calculation, timelapse, camera FTP worker and telemetry-v4 58-field schema are unchanged.

## Dashboard
- Simplified Live, Trends, Events and Advanced views; the Gallery view is removed.
- Live image, overall health, camera/FTP/control status, capture/upload freshness and key camera settings.
- Trends includes 24-hour, 7-day and 30-day subtabs, with brightness, image-quality, exposure and camera process-memory graphs.
- Events provides a concise chronological incident list; Advanced clearly exposes detailed system information.
- Live restores Raspberry Pi CPU, memory, process, storage and uptime statistics.
- Gallery image publishing and exact-set FTP reconciliation continue in the background; only its dashboard view was removed.
- Missing values display as unavailable, and the camera overlay continues to show Looking North East.

## Install
```bash
unzip HWS-Webcam-Control-50.3.3.zip
cd HWS-Webcam-Control-50.3.3
python3 verify_v50_3_3.py
sudo bash ./install_v50_3_3.sh
```

## Publish immediately
```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Rollback
```bash
sudo bash /mnt/weathercam/app/current/rollback_v50_3_3.sh
```
