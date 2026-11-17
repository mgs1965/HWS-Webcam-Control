# Harpenden Weather Camera V49.6

**Final deployment baseline.**

V49.6 is the dashboard/observability release based on the complete V49.5 source. Camera-control, exposure, mode thresholds, quality calculation, timelapse, camera FTP worker and telemetry-v4 58-field schema are retained.

## UI
- Restores the approved dark mock-up hierarchy with a large live image and prominent System Health panel.
- Persistent Camera / FTP / Telemetry / Control / Mode status strip.
- Live, 24 Hours, 7 Days, 30 Days, Gallery and Diagnostics views.
- Actual DAY / TWILIGHT / LOW LIGHT / NIGHT mode timeline.
- Separate graphs for incompatible units; logarithmic exposure plots; axis scales, time/date ticks and legends.
- Current/min/average/max summary on key Live charts.
- Gallery cards correlate images with nearest telemetry and support mode/Best filters.
- Settings renamed Diagnostics; missing values display `Not available`; unknown health is grey, not failure.
- Gallery publishing retains the V49.5 exact 48-file remote reconciliation and HTML-last commit.
- Looking North East overlay.

## Install
```bash
unzip HarpendenWeatherCamera-V49.6.zip
cd HarpendenWeatherCamera-V49.6
python3 verify_v49_6.py
sudo ./install_v49_6.sh
```

## Publish immediately
```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Rollback
```bash
sudo /mnt/weathercam/app/current/rollback_v49_6.sh
```
