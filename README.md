# Harpenden Weather Camera V51.0.1

V51.0.1 expands the health dashboard into a lightweight camera-operations control room. Camera-control behavior and telemetry-v4 (58 fields) remain unchanged.

## Dashboard

- **Live:** latest image, capture age, camera/FTP/control health, Raspberry Pi status, recommended checks, and timelapse/capture report.
- **Trends:** 24-hour, 7-day and 30-day image and Pi-health graphs. Warning/error events are marked on the timeline; each graph shows its source sample count and time span.
- **Reports:** daily capture completeness, health and timelapse summaries, with CSV export.
- **Archive:** browse the latest 48 available camera frames.
- **Events and Advanced:** recent incidents, camera diagnostics, publishing status and system details.
- Export the selected trend period as CSV. The dashboard refreshes automatically on the existing five-minute publication cycle.

Trend history is kept bounded for Raspberry Pi memory: the most recent 24 hours of capture telemetry remains full-resolution, while older 30-day history is sampled. Health snapshots remain at their recorded hourly cadence. Dashboard recommendations are observational and do not change camera settings.

## Install

Create `/etc/weathercam/dashboard.env` from `dashboard.env.example` and set `HWS_FTP_PASSWORD` before installing on a new host.

```bash
unzip HWS-Webcam-Control-51.0.1.zip
cd HWS-Webcam-Control-51.0.1
python3 verify_v51_0_1.py
sudo bash ./install_v51_0_1.sh
```

The installer preserves an existing `weathercam.service`; on a clean installation it installs the included unit after credential preflight.

## Publish immediately

```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Rollback

```bash
sudo bash /mnt/weathercam/app/current/rollback_v51_0_1.sh
```
