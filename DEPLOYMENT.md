# V54.8 Deployment

V54.8 adds scene analysis, a daily keogram, weekly/monthly timelapses and an optional weather overlay while retaining the V50.3.5 runtime reliability fixes and telemetry-v4 (58-field) contract. Camera-control behavior is unchanged.

## Pre-install

```bash
python3 verify_v54_8.py
```

For a clean install, create `/etc/weathercam/dashboard.env` from `dashboard.env.example` and set `HWS_FTP_PASSWORD`. The installer supplies `weathercam.service` only when no existing unit is registered and will not overwrite an on-disk unit file.

## Install

```bash
sudo bash ./install_v54_8.sh
```

## Confirm active release

```bash
readlink -f /mnt/weathercam/app/current
systemctl is-active weathercam.service
systemctl is-active weathercam-dashboard.timer
```

Expected release: `/mnt/weathercam/app/releases/HarpendenWeatherCamera-V54.8`. The dashboard publisher is a oneshot service and may be inactive between timer runs.

## Force one publication

```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Verify the generated dashboard

```bash
grep -E 'V54.8|Recommended checks|Timelapse|Daily reliability reports|Recent captures|CPU temperature|30 days' /mnt/weathercam/dashboard/dashboard.html | head
! grep -q '__DATA__' /mnt/weathercam/dashboard/dashboard.html
```

The dashboard displays recommended checks and historical readings but does not modify camera controls or send external alerts.

## Rollback

```bash
sudo bash /mnt/weathercam/app/current/rollback_v54_8.sh
```

## Replacing the old website (V54.8)

The dashboard publishes `index.html` (the original/new site chooser) and `indexnew.html` (Home), followed by Live, Graphs, Rainfall, Wind, Forecast, Webcam, Radar, Records, Compare, Almanac, Reports, News, Donate, About, Mobile and HWS Health. Every page has the same logo, title, button menu, current-page highlight and station disclaimer. About includes the station details; the Data page is retired. `health.html` uses the camera dashboard design with camera, weather/Meteobridge and Pi status, plus buttons for detailed health pages. `satellite.html` is available from Radar and uses Windy's satellite embed, with a direct provider link if embedding is unavailable. Visitors can switch units and theme using the bottom toolbar.

Graph, rainfall, wind and health filters use **Month** for the current calendar month in Europe/London, not a rolling 30-day window. Graphs and rainfall also offer a year selector for archived daily data. The live pages fetch uncached `weather-live.json`, fall back to `dashboard-data.json` if necessary, and never replace newer readings with older ones. The dashboard publishes a live snapshot on each publication; keep the weather-station service and live uploads enabled for updates between dashboard builds.

Recommended cut-over:

1. Set `DASHBOARD_FTP_DIR` to a test folder (for example `/public_html/new`) and publish there. Set `DASHBOARD_MEDIA_BASE` if the timelapse and keogram files live elsewhere (the camera uploads them to `FTP_UPLOAD_PATH`).
2. Set `HWS_LIVE_UPLOAD_SECONDS=15` for a live feel, and run `python3 weather_station.py --diagnose` to check units against the old console.
3. Run both sites side by side for 2 to 4 weeks, comparing readings.
4. Move `DASHBOARD_FTP_DIR` to the site root, keep the old pages for a while, then set `DASHBOARD_WRITE_REDIRECTS=1` (redirects are off by default so both sites can run in parallel) and copy the generated `redirects.htaccess` (never uploaded) to the root as `.htaccess` so old `*.php` links forward to the new pages.

Weather Underground, CWOP and WOW uploads are handled by the Meteobridge itself and are not affected.

### Adding news

From the installed release directory, load the dashboard environment and run:

```bash
set -a; . /etc/weathercam/dashboard.env; set +a
python3 weathercam_dashboard/dashboard.py \
  --add-news "Station Update" \
  --news-text "The weather station has been serviced." \
  --upload
```

This saves the entry to `/mnt/weathercam/logs/dashboard_news.json` and regenerates/uploads the site, including News and the Home news preview. For longer posts, use `--news-file /path/to/post.txt` instead of `--news-text`; optionally set `--news-date YYYY-MM-DD`. Omit `--upload` for a local preview. `DASHBOARD_NEWS_PATH` overrides the storage path and must be the same for the command and scheduled publisher. Entries survive release upgrades; existing site-content news and the bundled archive remain visible. Upload failures leave the local entry saved: retry publication with `--upload` without adding it again.

### Importing old Meteobridge history

```bash
set -a; . /etc/weathercam/dashboard.env; set +a
python3 weather_station.py --meteobridge 192.168.0.65 --backfill   # add --meteobridge-user/--meteobridge-password if needed
```

This asks the Meteobridge for each past day (daily high/low, mean humidity, rain, pressure extremes, gust) and stops after 45 empty days, writing `weather_station_archive.json` in the logs folder (`HWS_WEATHER_ARCHIVE_PATH`). It is safe to re-run; days already imported are skipped. The records, reports and year graph then include the old data at the next dashboard refresh. It only works for as long as the Meteobridge kept its history.
