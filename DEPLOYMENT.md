# V54.1 Deployment

V54.1 adds scene analysis, a daily keogram, weekly/monthly timelapses and an optional weather overlay while retaining the V50.3.5 runtime reliability fixes and telemetry-v4 (58-field) contract. Camera-control behavior is unchanged.

## Pre-install

```bash
python3 verify_v54_1.py
```

For a clean install, create `/etc/weathercam/dashboard.env` from `dashboard.env.example` and set `HWS_FTP_PASSWORD`. The installer supplies `weathercam.service` only when no existing unit is registered and will not overwrite an on-disk unit file.

## Install

```bash
sudo bash ./install_v54_1.sh
```

## Confirm active release

```bash
readlink -f /mnt/weathercam/app/current
systemctl is-active weathercam.service
systemctl is-active weathercam-dashboard.timer
```

Expected release: `/mnt/weathercam/app/releases/HarpendenWeatherCamera-V54.1`. The dashboard publisher is a oneshot service and may be inactive between timer runs.

## Force one publication

```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Verify the generated dashboard

```bash
grep -E 'V54.1|Recommended checks|Timelapse|Daily reliability reports|Recent captures|CPU temperature|30 days' /mnt/weathercam/dashboard/dashboard.html | head
! grep -q '__DATA__' /mnt/weathercam/dashboard/dashboard.html
```

The dashboard displays recommended checks and historical readings but does not modify camera controls or send external alerts.

## Rollback

```bash
sudo bash /mnt/weathercam/app/current/rollback_v54_1.sh
```

## Replacing the old website (V54.1)

The dashboard now publishes a full site: `index.html` (a chooser with tiles for `indexold.php` and `indexnew.html`; rename the old site's `index.php` to `indexold.php` on the server so the chooser works), `indexnew.html` (home, named so the old site's index keeps working in parallel; rename to `index.html` at cut-over), `console.html`, `graphs.html`, `forecast.html`, `webcam.html`, `radar.html`, `records.html`, `reports.html`, `almanac.html`, `data.html`, `health.html`, `rainfall.html`, `wind.html`, `news.html`, `mbhealth.html`, `pihealth.html`, `station.html`, `about.html`, `mobile.html`, plus `site.css`, `site.js` and `favicon.svg`. Visitors can switch units (°C/°F, mph/km/h, hPa/inHg) and dark/light theme from the small toolbar at the bottom right.

Recommended cut-over:

1. Set `DASHBOARD_FTP_DIR` to a test folder (for example `/public_html/new`) and publish there. Set `DASHBOARD_MEDIA_BASE` if the timelapse and keogram files live elsewhere (the camera uploads them to `FTP_UPLOAD_PATH`).
2. Set `HWS_LIVE_UPLOAD_SECONDS=15` for a live feel, and run `python3 weather_station.py --diagnose` to check units against the old console.
3. Run both sites side by side for 2 to 4 weeks, comparing readings.
4. Move `DASHBOARD_FTP_DIR` to the site root, keep the old pages for a while, then set `DASHBOARD_WRITE_REDIRECTS=1` (redirects are off by default so both sites can run in parallel) and copy the generated `redirects.htaccess` (never uploaded) to the root as `.htaccess` so old `*.php` links forward to the new pages.

Weather Underground, CWOP and WOW uploads are handled by the Meteobridge itself and are not affected.

### Importing old Meteobridge history

```bash
set -a; . /etc/weathercam/dashboard.env; set +a
python3 weather_station.py --meteobridge 192.168.0.65 --backfill   # add --meteobridge-user/--meteobridge-password if needed
```

This asks the Meteobridge for each past day (daily high/low, mean humidity, rain, pressure extremes, gust) and stops after 45 empty days, writing `weather_station_archive.json` in the logs folder (`HWS_WEATHER_ARCHIVE_PATH`). It is safe to re-run; days already imported are skipped. The records, reports and year graph then include the old data at the next dashboard refresh. It only works for as long as the Meteobridge kept its history.
