# Harpenden Weather Camera V53.9

V53.9 adds camera and image intelligence: scene analysis (cloud cover, fog, lens droplets, frozen/blocked view, focus drift), an optional weather-station overlay, a daily keogram, and weekly/monthly timelapses. Camera-control behavior and telemetry-v4 (58 fields) remain unchanged.

## Camera and image features

- **Scene analysis:** observational only; results appear on the dashboard Live view, in `camera_status.json` and in `logs/scene/`. Alerts feed the dashboard's recommended checks.
- **Weather overlay:** write a JSON file (`updated` ISO time plus `temperature_c`, `humidity_percent`, `pressure_hpa`, `wind_speed_mph`, `wind_gust_mph`, `wind_direction_deg`, `rain_rate_mm_h`) to `HWS_WEATHER_DATA_PATH` (default `/mnt/weathercam/logs/weather_station.json`). Data older than 15 minutes is ignored. To populate it from a Weather Display `clientraw.txt`, run `CLIENTRAW_URL=https://your-site/clientraw.txt python3 weather_station.py --interval 60` (or `--once`); the installer ships `weathercam-weather-station.service`, which runs it with retries once `CLIENTRAW_URL` is set in `/etc/weathercam/dashboard.env`; stale or malformed files are never written. It also adds 1-hour trends from `clientrawhour.txt` and writes `weather_station_history.json` (30 daily extremes and year records) from `clientrawdaily.txt` and `clientrawextra.txt`, plus `weather_station_series.json` (rolling 24-hour samples every 5 minutes that feed the dashboard graphs). It also reads UV (token 79), solar (127), lightning counts and maximum gusts. Weekly and monthly timelapses are always created; set `HWS_UPLOAD_WEEKLY_TIMELAPSE=0` and/or `HWS_UPLOAD_MONTHLY_TIMELAPSE=0` in `/etc/weathercam/dashboard.env` to stop uploading them.
- **Keogram:** one image per day on the dashboard Archive, uploaded as `latest_keogram.png`.
- **Weekly/monthly timelapses:** uploaded as `latest_weekly_timelapse.mp4` and `latest_monthly_timelapse.mp4`.

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
unzip HWS-Webcam-Control-53.9.zip
cd HWS-Webcam-Control-53.9
python3 verify_v53_9.py
sudo bash ./install_v53_9.sh
```

The installer preserves an existing `weathercam.service`; on a clean installation it installs the included unit after credential preflight.

## Publish immediately

```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Rollback

```bash
sudo bash /mnt/weathercam/app/current/rollback_v53_9.sh
```
