# Harpenden Weather Camera V50.3.5

**Runtime reliability and deployment corrections to V50.**

V50.3.5 corrects Raspberry Pi throttling status decoding, ensures completed timelapses update the daily health report, validates persisted quality state, contains camera restart failures, and fixes controller configuration fingerprints. It also provides a `weathercam.service` unit for clean installs while preserving existing units. It retains the V50.3.4 camera-mode performance panel, the V50.3.3 dashboard rendering fix and the telemetry-v4 58-field schema.

## Dashboard
- Simplified Live, Trends, Events and Advanced views; the Gallery view is removed.
- Live image, overall health, camera/FTP/control status, capture/upload freshness and key camera settings.
- Trends includes 24-hour, 7-day and 30-day subtabs, with brightness, image-quality, exposure and camera process-memory graphs.
- Trends includes last-24-hour mode summaries and transitions, with descriptive averages and low-sample indicators.
- Raspberry Pi throttling flags use the documented `vcgencmd get_throttled` bit fields.
- Events provides a concise chronological incident list; Advanced clearly exposes detailed system information.
- Live restores Raspberry Pi CPU, memory, process, storage and uptime statistics.
- Gallery image publishing and exact-set FTP reconciliation continue in the background; only its dashboard view was removed.
- Missing values display as unavailable, and the camera overlay continues to show Looking North East.

## Install
Create `/etc/weathercam/dashboard.env` from `dashboard.env.example` and set `HWS_FTP_PASSWORD` before installing on a new host.

```bash
unzip HWS-Webcam-Control-50.3.5.zip
cd HWS-Webcam-Control-50.3.5
python3 verify_v50_3_5.py
sudo bash ./install_v50_3_5.sh
```

## Publish immediately
```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Rollback
```bash
sudo bash /mnt/weathercam/app/current/rollback_v50_3_5.sh
```
