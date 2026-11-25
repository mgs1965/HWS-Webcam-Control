# V2026.11.25.08 Deployment

V2026.11.25.08 adds selectable-year daily and monthly Meteobridge health trends, while retaining the telemetry-v4 (58-field) contract.

## Pre-install

```bash
python3 verify.py
```

For a clean install, create `/etc/weathercam/dashboard.env` from `dashboard.env.example` and set `HWS_FTP_PASSWORD`. The installer supplies `weathercam.service` only when no existing unit is registered and will not overwrite an on-disk unit file.

## Install

```bash
sudo bash ./install.sh
```

## Confirm active release

```bash
readlink -f /mnt/weathercam/app/current
systemctl is-active weathercam.service
systemctl is-active weathercam-dashboard.timer
```

Expected release: `/mnt/weathercam/app/releases/HarpendenWeatherCamera-V2026.11.25.08` (an updated V2026.11.25.08 installation uses a timestamped suffix). The dashboard publisher is a oneshot service and may be inactive between timer runs.

## Force one publication

```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weathercam_dashboard/dashboard.py --upload'
```

## Verify the generated dashboard

```bash
grep -E 'V2026.11.25.08|Recommended checks|Timelapse|Daily reliability reports|Recent captures|CPU temperature|30 days' /mnt/weathercam/dashboard/dashboard.html | head
! grep -q '__DATA__' /mnt/weathercam/dashboard/dashboard.html
```

The dashboard displays recommended checks and historical readings but does not modify camera controls. Optional health alerts are sent by `alerts.py` (below).

## Updating from a release
`bash update.sh --check` reports whether a newer GitHub release exists; `bash update.sh` downloads it, runs `install.sh`, and rolls back automatically if the camera does not start. The repository is private, so set `GITHUB_TOKEN` (read access to contents) in `/etc/weathercam/dashboard.env` or the environment. There is no automatic update timer by default.

## Health alerts
`alerts.py` (run every 5 minutes by `weathercam-alerts.timer`) reports a stale camera image, stale weather data, a full disk or a stopped service, repeats after `HWS_ALERT_REPEAT_HOURS`, and sends a recovery message. Set `HWS_ALERT_NTFY_URL`, `HWS_ALERT_WEBHOOK_URL` or the `HWS_ALERT_SMTP_*` settings in `/etc/weathercam/dashboard.env`; the installer enables the timer only when one is set. `python3 alerts.py --test` sends a test message.

## Releasing (maintainers)
`python3 release.py 2026.11.25.08 "What changed"` bumps the version everywhere, updates the changelog and manifest, runs `verify.py` and the tests, and builds the zip. Add `--publish` to commit, push `main` and create the GitHub release.

## Rollback

```bash
sudo bash /mnt/weathercam/app/current/rollback.sh
```

## Replacing the old website

The dashboard publishes `index.html` (the original/new site chooser) and `indexnew.html` (Home), followed by Live, Graphs, Rainfall, Wind, Forecast, Webcam, Radar, Records, Compare, Almanac, Reports, News, Donate, About, Mobile and HWS Health. Every page has the same logo, title, button menu, current-page highlight and station disclaimer. About includes the station details; the Data page is retired. `health.html` uses the camera dashboard design with camera, weather/Meteobridge and Pi status, plus buttons for detailed health pages. `satellite.html` is available from Radar and uses Windy's satellite embed, with a direct provider link if embedding is unavailable. Visitors can switch units and theme using the bottom toolbar.

Graph, rainfall, wind and health filters use **Month** for the current calendar month in Europe/London, not a rolling 30-day window. Graphs offers daily and monthly summaries for the selected year; 24-hour data is current only. Rainfall monthly totals show the selected year, based on the days actually recorded. Meteobridge health trends accumulate as readings are collected; existing archived daily sensor averages appear if present. Home, Live and Mobile show the time and age of the last reading and warn after 10 minutes or on refresh failure. The live pages fetch uncached `weather-live.json`, fall back to `dashboard-data.json` if necessary, and never replace newer readings with older ones. Only the weather-station service uploads `weather-live.json`; dashboard publication must not overwrite it. Keep the service and live uploads enabled for updates between dashboard builds.

The default coordinates are 51.829105, -0.380987. Existing `/etc/weathercam/dashboard.env` files are preserved by the installer: update `DASHBOARD_LATITUDE` and `DASHBOARD_LONGITUDE` there if they still contain the old values. Check the `Console` page on the deployed host: it embeds `/Weather34/index.php` and links to it directly if the web server blocks framing.

The console frame sizes itself to same-origin Weather34 content; if access is blocked by the browser or a redirect, it uses a fixed fallback height. The health navigation offers the same dashboard views and detailed health pages on each health page.

Meteobridge uptime (`data11num`) is in hours; voltage and power are in volts and watts. Soil wetness is measured in centibars (0–200), not percent. Signal charts show the station's reported values in dB, with five-minute minimum and maximum readings and daily extrema for the year view. Base-board and RF-board temperatures use `thb9temp` and `thb0temp`. Older readings are available only if recorded or imported from the Meteobridge. Run `--diagnose` against the station to confirm the readings and selectors.

Meteobridge health trends offer daily and monthly views by year for all available stored health readings. Monthly values are averages of recorded daily values, except for uptime (last available reading) and signal strength (daily extrema). Years or individual readings not retained locally or imported from the Meteobridge cannot be shown.

If live weather is unavailable, check `systemctl status weathercam-weather-station.service` and `journalctl -u weathercam-weather-station.service -n 50 --no-pager`. Check the Meteobridge connection and credentials in `/etc/weathercam/dashboard.env`, and confirm `DASHBOARD_FTP_DIR` is the same directory used by the dashboard publisher. Avoid sharing the environment file or its passwords. Restart the fetcher after correcting its configuration: `sudo systemctl restart weathercam-weather-station.service`.

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

The environment file is root-readable; load it as root and run the import as the station user:

```bash
sudo bash -c 'set -a; . /etc/weathercam/dashboard.env; set +a; exec sudo -u mgs -E /usr/bin/python3 /mnt/weathercam/app/current/weather_station.py --backfill'
```

This asks the Meteobridge for each past day (daily high/low, mean humidity, rain, pressure extremes, gust) and stops after 45 empty days, writing `weather_station_archive.json` in the logs folder (`HWS_WEATHER_ARCHIVE_PATH`). By default it waits two seconds before each request, allows 60 seconds per request and retries transient failures twice, with a two-second delay. It saves progress even if interrupted or a request fails; rerun to resume. A failed or interrupted backfill exits nonzero and reports the stopped date. The records, reports and year graph include the old data at the next dashboard refresh. It only works for as long as the Meteobridge kept its history.

Backfill version 4 requests daily signal minima and maxima, Meteobridge health readings, base-board (`thb9temp`) and RF-board (`thb0temp`) mean temperatures, and ground, soil and greenhouse sensor means. Re-running it revisits earlier imported days and preserves previously saved fields when a sensor has no value. Choose an appropriate `--backfill DAYS` limit: the default can take several hours. Only readings retained by the Meteobridge can be imported; unavailable historical values remain blank.

Live requests default to a 20-second timeout and two retries for transient errors (including HTTP 504), with a two-second delay; authentication errors are not retried. Set `HWS_METEOBRIDGE_TIMEOUT`, `HWS_METEOBRIDGE_RETRIES`, `HWS_METEOBRIDGE_RETRY_DELAY`, `HWS_BACKFILL_TIMEOUT` or `HWS_BACKFILL_DELAY` in `/etc/weathercam/dashboard.env` to change these, or use `--request-timeout`, `--request-retries`, `--retry-delay`, `--backfill-timeout` and `--backfill-delay` on the command line.

### Meteobridge credentials

If a password has been exposed, change it in the Meteobridge's administration interface and update `/etc/weathercam/dashboard.env` locally with `HWS_METEOBRIDGE_USER` and `HWS_METEOBRIDGE_PASSWORD`. Keep the file owned by root with mode `0600`; restart `weathercam-weather-station.service` after changing it. Do not paste credentials into chat, command arguments, or logs. For an interactive one-off backfill, enter the new password without echo or shell history:

```bash
read -rsp 'Meteobridge password: ' HWS_METEOBRIDGE_PASSWORD; echo
export HWS_METEOBRIDGE_PASSWORD HWS_METEOBRIDGE_USER=meteobridge
python3 weather_station.py --meteobridge 192.168.0.65 --backfill
unset HWS_METEOBRIDGE_PASSWORD
```

### Editing news by hand (no release needed)

The News page is driven by `/mnt/weathercam/logs/dashboard_news.json`, a list of `{"date": "YYYY-MM-DD", "time": "HH:MM", "title": "...", "text": "..."}` entries (the page sorts them). Edit the file with any editor, then run `python3 weathercam_dashboard/dashboard.py` (or wait for the dashboard timer) to republish. Deleting an entry removes it from the site.

`install.sh` copies the bundled archive of existing articles into this file once (`dashboard.py --import-news-archive`, marker `dashboard_news.json.archive-imported`). After that only the file is used, so releases never overwrite or resurrect articles.

## Automation, backups, health checks and CI

- **Self-test:** `cd /mnt/weathercam/app/current && bash selftest.sh` (add `--notify` to send a test alert) prints PASS/WARN/FAIL for the camera, weather feed, site, timers, news file, health checks and update check.
- **Automatic updates:** put `HWS_AUTO_UPDATE=1` and `GITHUB_TOKEN=...` in `/etc/weathercam/dashboard.env`, then `sudo systemctl enable --now weathercam-update.timer` (install.sh does this when the flag is set). It runs `update.sh` at about 03:30; a failed install rolls back and leaves `logs/update_failed`, which `alerts.py` reports until the next success. Output: `journalctl -u weathercam-update`.
- **Backups:** set `HWS_BACKUP_DEST` (`user@host:/path` over ssh/rsync, a mounted folder, or plain FTP: `HWS_BACKUP_DEST=ftp://host/dir/` with `HWS_BACKUP_FTP_USER` and `HWS_BACKUP_FTP_PASSWORD`; set `HWS_BACKUP_FTP_TLS=1` if the host supports FTPS. Keep the folder outside the public web root). A second destination goes in `HWS_BACKUP_DEST2` (FTP login: `HWS_BACKUP_FTP2_USER` / `HWS_BACKUP_FTP2_PASSWORD`). `weathercam-backup.timer` runs `backup.sh` at 02:30, keeps the last `HWS_BACKUP_KEEP` (14) archives in `/mnt/weathercam/backups` and copies each to the destination. `HWS_BACKUP_INCLUDE_ENV=1` also stores `dashboard.env` (contains secrets: only use a trusted destination). Failures leave `logs/backup_failed` and are alerted. `HWS_BACKUP_REMOTE_KEEP_DAYS=N` deletes this script's archives older than N days from the destinations (off by default; a host given as `ftp.example.com/dir/` gets `ftp://` added, and `ftps://` forces TLS).
- **Restore:** `bash restore.sh --list`, `bash restore.sh --latest --dry-run`, then `sudo bash restore.sh --latest` (or an archive path; `--yes` skips the prompt, `--with-env` also restores `dashboard.env`). On a new SD card first download an archive: `curl --user USER:PASS -o backup.tar.gz ftp://ftp.example.com/backups/hws-backup-....tar.gz`, then `sudo bash restore.sh backup.tar.gz`. Restart afterwards: `sudo systemctl restart weathercam weathercam-dashboard`.
- **Weekly digest:** add `HWS_DIGEST=1` and re-run the installer (or `sudo systemctl enable --now weathercam-digest.timer`). It sends last week's rain, extremes, strongest gust and open problems every Monday at 08:00 through the alert channels. Preview: `python3 digest.py --print`.
- **Pi health page:** shows power/throttling, SD-card errors, filesystem state, last backup and last update check.
- **Storage and board health:** `alerts.py` also reports a read-only filesystem, inode exhaustion, SD-card/kernel I/O errors, Pi under-voltage or throttling and CPU temperature (`HWS_ALERT_INODE_PERCENT`, `HWS_ALERT_TEMP_C`).
- **CI:** `.github/workflows/test.yml` runs verify.py, the unit tests, the headless-Chrome smoke test and the release build on every push and pull request.
