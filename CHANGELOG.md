#### V54.3

- Rainfall page fixed: 24 h rain-rate chart reads the right data; `--backfill` falls back to `rain0total-daysum` and refills days missing rain (re-run `weather_station.py --backfill`).
- Reports: monthly/yearly rain-days total is now a sum. Records, tiles and mobile no longer overspill.
- Pi health: axis scales on charts and a readable disk forecast. Mobile page polls live data immediately.
- Camera dashboard tiles follow the site theme. Station page shows Davis Vantage Pro 2 Plus with UV and Solar sensors.
- New Donate page with PayPal button (`DASHBOARD_PAYPAL_BUTTON_ID` to override); `donate.php` redirects to it.

#### V54.2

- Home page loads live weather immediately, shows a "data is N minutes old" warning when the station goes quiet, trend arrows with 24 h high/low on temperature and pressure, live alert banner, and a "Share today's weather" link.
- Weather alerts for frost, strong gusts and heavy rain, by email (SMTP) and/or ntfy push, once per 6 hours per alert; thresholds and settings in `dashboard.env.example`.
- `share.png`: auto-generated 1200x630 social card of the current weather (needs Pillow).
- New `compare.html`: overlay any two months or years (daily highs, cumulative rain, summary table).
- Reports can be printed or saved as PDF; print stylesheet for all pages.
- Mobile layout polish; PNG logo and favicon.

#### V54.1

- New `index.html` site chooser in the racing-green theme: tiles for the original site (`indexold.php`) and the new site (`indexnew.html`), a short note that the new site is under development, and a feedback box that emails info@harpendenweatherstation.co.uk. Rename the old site's `index.php` to `indexold.php` on the server.
- Copyright footer "© 2026 Mark Sanders · Contact Me" on every page, including the camera dashboard.

#### V54.0

- New pages: `news.html` (49 entries imported from the old site, plus your own via `DASHBOARD_SITE_CONTENT` `news`), `rainfall.html` (rain rate, daily, monthly, cumulative by year, year table, wettest days, built from the Meteobridge backfill), `wind.html` (speed-banded wind rose for 24 h, 7 d, 30 d), `mbhealth.html` (Meteobridge link, clientraw comparison, history coverage) and `pihealth.html` (CPU, memory, disk, uptime and trends).
- Home page (`indexnew.html`): "Today in Harpenden" line (day length and this date in earlier years), latest news, sunrise and sunset highlight videos, racing-green theme, logo and keogram banner.
- Daily timelapse now also builds `sunrise_YYYYMMDD.mp4` and `sunset_YYYYMMDD.mp4` (±60 min, `HWS_HIGHLIGHT_MINUTES`) and uploads them with `latest_sunrise.mp4`/`latest_sunset.mp4`.
- Scene log records wind direction and gust, so the 7 and 30 day wind roses build up over time.
- Records page shows earlier records from the old site; `indexnew.html` stays unpublished-as-index and redirects stay opt-in.

#### V53.9

- Site pages to replace the old website: `index.html` (home), `webcam.html`, `radar.html`, `records.html`, `reports.html` (day, month and year tables with CSV), `almanac.html`, `data.html`, `health.html`; About shows news and donate text.
- Unit toolbar (°C/°F, mph/km/h, hPa/inHg) and dark/light theme, favicon, and a generated `redirects.htaccess` for old `.php` URLs.
- `weather_station.py --backfill` imports old Meteobridge daily history into `weather_station_archive.json`; graphs and records use it, keeping up to about 11 years of daily rows.
- `DEPLOYMENT.md` documents the cut-over from the old site.

#### V53.8

- Wind direction is shown as 16-point compass names (N, NNE, NE ...) in the live strip, Weather tab, sparkline and source comparison.
- New `console.html`: live console (temperature, wind compass, pressure, rain, solar/UV, sun and moon, webcam, year records) refreshing from `weather-live.json`.
- New `graphs.html`: 24 hour, 7 day, 30 day and year charts, with a daily rainfall total. The daily log now records each day's rainfall (`rain_mm`), so year rainfall builds up from this release.
- New `forecast.html`: 8-day and 48-hour forecast from MET Norway (the data behind yr.no), cached for an hour (`DASHBOARD_FORECAST`, `DASHBOARD_FORECAST_REFRESH_MINUTES`); the camera computer needs internet access.
- New `about.html`, `station.html` and `mobile.html` (phone view); text can be customised with `DASHBOARD_SITE_CONTENT`.
- All pages share one navigation bar and are uploaded with the dashboard.

#### V53.7

- New Insights tab: quality forecast (next hour and after sunset), "why was quality poor?", lens-maintenance predictor, weather correlations, daily summaries, monthly and year-to-date statistics (persisted in `dashboard_daily_stats.json`).
- Smart events: rapid fog formation, sudden visibility collapse, sunset cloud break, heavy rain onset, possible snow.
- Weather tab: Temperature metric, live strip (`weather-live.json`, `HWS_LIVE_UPLOAD_SECONDS`), stale-station banner and recommendation; page auto-reloads every 5 minutes.
- `weather_station.py --diagnose` prints raw vs converted Meteobridge values for unit checks.

#### V53.6

- On start-up the weather service back-fills the local minute log (last hour) and daily log (last 30 days) from the clientraw hour/daily files, without overwriting real readings. Needs both `CLIENTRAW_URL` and `HWS_METEOBRIDGE_URL`; seed before setting `HWS_CLIENTRAW_ENABLED=0`.
- Meteobridge year records (`-ymax`/`-ymin`) confirmed working on the device.

#### V53.5

- New `HWS_CLIENTRAW_ENABLED` option (set 0) switches off the clientraw feed; the weather service then uses only the Meteobridge.
- Meteobridge-only mode keeps a local minute log and daily log, so hour charts, 1h trends and 30-day history build up from the Meteobridge readings (both modes record them).
- Year records are read from the Meteobridge (`-ymax`/`-ymin`, untested on the device).
- The raw "Weather data" tab and the source comparison need clientraw and stay empty when it is off.
- `CLIENTRAW_URL` is no longer required when `HWS_METEOBRIDGE_URL` is set.

#### V53.4 - 2026-11-21
- Weather: new "Source comparison" table on the Weather tab showing the clientraw value, the Meteobridge value, the difference and a match/differs result for each shared field (temperature, humidity, pressure, wind, gust, direction, dew point, rain, UV, solar, max gust, lightning). Useful for checking units.
- Weather station: saves both readings to `weather_station_compare.json` (`HWS_WEATHER_COMPARE_PATH`, `--compare-output`) whenever both sources are available. Restart the weather service after installing.

#### V53.3 - 2026-11-21
- Weather station: Meteobridge login support. Set `HWS_METEOBRIDGE_PASSWORD` (and `HWS_METEOBRIDGE_USER`, default `meteobridge`) in `/etc/weathercam/dashboard.env` when the Meteobridge answers HTTP 401; the log now hints at this.

#### V53.2 - 2026-11-21
- Weather station: can read the Meteobridge directly (`HWS_METEOBRIDGE_URL=192.168.0.65` or `--meteobridge`) using its template.cgi live-data API, with the clientraw files kept as the fallback and for the hour/daily/extra data. Live values override clientraw where both exist.
- New values from the Meteobridge: heat index, wet bulb, wind chill, sunshine hours, lightning energy and the bridge's data age, shown on the Weather tab.
- Units requested: wind in mph, rain in mm, pressure sea-level hPa. Confirm against the console after installing.
- Set `HWS_METEOBRIDGE_URL` in `/etc/weathercam/dashboard.env`, then restart the weather service.

#### V53.1 - 2026-11-21
- Dashboard: the weather station panel moves from the Live page to its own "Weather" tab (the raw clientraw tab stays as "Weather data").
- Dashboard: new graphs for dew point, rain today, wind direction, lightning today, sky clarity and droplet score (24 h), and humidity and pressure for the last hour.

#### V53.0 - 2026-11-22
- Scene analysis: with the sun below 10 degrees the cloud estimate now counts only pixels that depart from their own row's median red/blue ratio, so a warm clear sunset sky no longer reads as ~40-50% cloud (the reported sunset image drops from 52% to 2%).
- Dashboard: `dashboard.py` split into `astronomy.py`, `analytics.py`, `station.py` and `recommendations.py` (loaded by `dashboard.py`; no behaviour change).
- Tests: added coverage for the low-sun cloud estimate and the module split. Live-data items still to confirm on the Pi: midday UV, hour-file minute order, lightning distance unit, gust-record unit.

#### V52.17 - 2026-11-21
- Dashboard: solar cloud cross-check (clear-sky estimate from sun elevation vs measured solar W/m2, compared with the camera's cloud cover; a large disagreement suggests a dirty or fogged lens).
- Dashboard: 30-day charts (daily high, low, lowest pressure), last-hour minute charts (wind, gust, temperature, solar) from the hour file, wind rose, and a 24-hour station summary.
- Dashboard: year-to-date record alerts (temperature and pressure), frost/freezing notes, and fog-condition and lightning entries in the event timeline.
- Camera overlay: adds gust, solar, UV and lightning to the weather line (set `HWS_OVERLAY_STATION_EXTRAS=0` to disable).
- Weather station: the rolling series now also stores wind direction, dew point, rain, lightning count and distance.
- Not included: the hour file on this station has no 24-hour solar/UV arrays (only 482 fields), so the hourly graphs cover the last hour; the daily rain block looked like a constant placeholder and the gust-record unit is unknown, so neither is charted or alerted on.

#### V52.16 - 2026-11-21
- Dashboard: new "Weather data" tab with sub-tabs for the live, hour, daily and extra clientraw files, showing every field number, label, value and unit (knots also shown in mph) with a filter box. Labels come from `weathercam_dashboard/weather_labels.json`.
- Weather station: the raw tokens of all four files are written to `weather_station_raw.json` (`HWS_WEATHER_RAW_PATH`, `--raw-output`) for the tab. The tab fills in after the weather service restarts.

#### V52.15 - 2026-11-21
- Timelapse: weekly and monthly videos have separate upload switches (`HWS_UPLOAD_WEEKLY_TIMELAPSE`, `HWS_UPLOAD_MONTHLY_TIMELAPSE`, default on). When off, the video is still created and kept, just not uploaded; daily uploads are unaffected.
- Weather station: UV index now read from the documented token 79 (V52.13 wrongly used token 34, which is solar percent of maximum). Added lightning counts, last-strike distance and maximum gusts (today and last hour).
- Weather station: new rolling 24-hour `weather_station_series.json`; the dashboard graphs (temperature, humidity, pressure, wind, gust, solar, UV) now draw from it instead of the scene logs, with scene logs as fallback. Cloud cover and fog index still come from the camera.
- Dashboard: lightning and strong-gust notes in the weather insight list; max gust and lightning metrics on the card. The 1-hour gust note previously never appeared because the value was filtered out; fixed.

#### V52.14 - 2026-11-20
- Dashboard: weather station graphs now have value scales (max/mid/min) and a time axis with grid lines.

#### V52.13 - 2026-11-20
- Weather station: reads UV index (clientraw token 34) and solar radiation in W/m2 (token 127) from the Davis VP2 sensors.
- Dashboard: Solar and UV metrics plus 24-hour sparklines on the Weather station card; both are recorded in scene history.

#### V52.12 - 2026-11-20
- Dashboard: new "Weather station" card with dew point, pressure, 1-hour changes, rain rate, fog risk, plain-language reasons (for example humidity close to the dew point, a fast temperature drop, strong gusts, rain), 24-hour temperature/humidity/cloud/fog sparklines from the scene history, and 7-day plus year-record temperatures from `weather_station_history.json`.
- Scene: new `fog_risk` (LOW/MODERATE/HIGH) from the air/dew-point spread and humidity, available day and night and recorded in scene history.
- Lens: at NIGHT with exposure above 2000 ms (`NIGHT_LENS_TOLERANT_EXPOSURE_US`) a sharpness warning no longer reports lens `DEGRADED`; a critical sustained loss still reports `POSSIBLE OBSTRUCTION`.

#### V52.11 - 2026-11-20
- Weather station: `weather_station.py` now also reads `clientrawhour.txt` (adds 1-hour temperature, humidity and pressure change and peak gust to `weather_station.json`; recorded in scene history with the dew point) and writes `weather_station_history.json` (`HWS_WEATHER_HISTORY_PATH`) every 30 minutes with 30 days of daily temperature/pressure extremes from `clientrawdaily.txt` and year records from `clientrawextra.txt`. Sibling files are located next to `CLIENTRAW_URL`; any that fail are skipped without affecting live data.

#### V52.10 - 2026-11-20
- New: `weather_station.py` fetches a Weather Display `clientraw.txt` (`CLIENTRAW_URL`) and writes `weather_station.json` for the existing weather overlay, status file and scene history. Stale, malformed or out-of-range data is never written; network errors are retried with back-off and the loop exits after 10 consecutive failed cycles so systemd restarts it.
- New: `systemd/weathercam-weather-station.service` (Restart=on-failure, start-limit protected, refuses to start without `CLIENTRAW_URL`); the installer installs it and enables it only when `CLIENTRAW_URL` is set.

#### V52.9 - 2026-11-20
- Fix: partly broken cloud still read 100% because the uniform-sky shortcut was too loose; its red/blue spread limit is lowered from 0.08 to 0.04.

#### V52.8 - 2026-11-20
- Fix: cloud cover read ~90-100% with clear blue gaps in the sky; the red/blue cloud threshold is raised from 0.62 to 0.80.

#### V52.7 - 2026-11-20
- Dashboard: Control status `IDLE` (no exposure/gain change needed recently) now shows green instead of grey.

#### V52.6 - 2026-11-20
- Dawn brightness filter: NIGHT/LOW LIGHT before solar noon use `DAWN_BRIGHTNESS_FILTER_ALPHA` (0.1 instead of 0.2) to stop gain ping-pong.
- Night quality: NIGHT frames are labelled GOOD/DARK/NOISY/WASHED; changes log `[NIGHT QUALITY]` and raise `night_quality_*` audit events.
- Control ACK retry: a timed-out control is resubmitted once with `CONTROL_ACK_RETRY_CAPTURES` extra captures before reconciling.
- Mode-aware exposure cap: at dawn the NIGHT exposure cap tapers from 4.5 s to the LOW LIGHT cap between -8 and -5 degrees, so long exposures do not carry into the transition.
- White balance by mode: dawn LOW LIGHT keeps the locked NIGHT colour gains (`LOW_LIGHT_DAWN_AWB_LOCK`) instead of re-running Auto AWB.

#### V52.5 - 2026-11-20
- Dashboard: new "Sun, moon & modes" card with next predicted mode change, sunrise/sunset, golden hours, day length, moon phase, a mode strip for today and a 24-hour event strip.
- Dashboard: daily calendar heatmap (5 weeks) with day detail, timelapse library (daily/weekly/monthly), keogram history (last 7 days, also uploaded to `keograms/`), analogue gain trend chart, PNG download for each chart, disk-fill forecast, FTP outage/recovery counts and a red night mode.
- Fix: `[MODE TRANSITION]` log lines now appear in the dashboard events list (it was filtering for a tag that is never logged).

#### V52.4 - 2026-11-20
- Fix: cloud cover under-reported uniform overcast skies (71% "mostly cloudy" when 100% cloud); the red/blue threshold is lowered to 0.62 and a uniform cloud-coloured sky now reads 100%.
- Fix: control ACK gain tolerance scales with the requested gain (12%), ending the 2.12/2.35 reconcile loop and timeout warnings during long pre-dawn exposures.
- Logging: `MODE TRANSITION` lines include exposure and gain.

#### V52.3 - 2026-11-20
- Reliability: weekly/monthly timelapse attempts are counted per day (3 per day), so a bad night no longer stops retries until restart; giving up is logged and audited.
- Reliability: daily videos are checked for compatible codec/size/pixel format before joining; incompatible sets (or a failed stream copy) fall back to a libx264 re-encode.
- Dashboard: weekly/monthly timelapse status (waiting, building, failed, complete) is shown on the Sky & scene card.
- Fix: daily health expected captures are based on monitored uptime, so a restart no longer reports a false DEGRADED day.
- Dashboard: Sky, Cloud cover, Visibility and Lens show "Paused (night)" instead of N/A when scene analysis is not running.

#### V52.2 - 2026-11-20
- Fix: weekly/monthly timelapses failed validation (5.12 fps) because daily videos with different track timescales (1/15360 vs 1/90000) were joined by stream copy. Each daily video is now rewritten to a 90 kHz timescale before joining; this replaces the V52.1 fps retiming, which did not address the cause.

#### V52.1 - 2026-11-19
- Fix: daily videos from earlier releases with a different frame rate are retimed to 30 fps before joining, so weekly/monthly timelapses pass validation (the first weekly build failed at 5.12 fps).

#### V52.0 - 2026-11-19
- Camera/image: new `scene_analysis.py` estimates cloud cover, fog/haze, lens droplets, frozen and blocked views and focus drift; alerts are logged, audited and shown in dashboard recommended checks. Scene history is kept in `logs/scene/` (30 days).
- Camera/image: optional weather-station JSON (`HWS_WEATHER_DATA_PATH`, default `logs/weather_station.json`) is validated and shown in a top overlay bar, the status file and the dashboard.
- Camera/image: new `keogram.py` builds a daily keogram (one slice per minute) uploaded as `keogram_YYYYMMDD.png` and `latest_keogram.png`, and shown in the dashboard Archive.
- Camera/image: weekly (`weekly_timelapse_YYYYMMDD.mp4`) and monthly (`monthly_timelapse_YYYYMM.mp4`) summary timelapses are joined from existing daily videos and uploaded as `latest_weekly_timelapse.mp4` / `latest_monthly_timelapse.mp4`.
- Retention: daily videos are kept 37 days (was 30) so the monthly build is complete; weekly 365 days, monthly 1095 days, keograms 90 days.
- Camera control and telemetry-v4 (58 fields) are unchanged; new data is additive in `camera_status.json`.
- Release: archives are named `HWS-Webcam-Control-<version>.zip` and extract to `HWS-Webcam-Control-<version>/`; `build_release.py` builds it from `manifest.json`.

#### V51.0.2 - 2026-11-19
- Dashboard: alert thresholds are configurable through `DASHBOARD_*` variables in `dashboard.env` (see `dashboard.env.example`).
- Dashboard: Events view can be filtered by severity, date range and message text; event severities now display correctly.
- Dashboard: brightness, quality and exposure graphs show camera-mode bands and sunrise/sunset lines; added a best/worst image-quality summary.
- Dashboard: latest timelapse can be played in the page (size-limited, uploaded only when changed).
- Dashboard: a banner warns when the page is offline or its data is older than `DASHBOARD_STALE_MINUTES`.

#### V51.0.1 - 2026-11-19
- Dashboard: critical disk usage is reported when free space is unavailable, unknown Pi throttling is no longer shown as inactive, and urgent health reasons are listed first.
- Dashboard: log events now carry timestamps, FTP connections are always closed, and an empty remote gallery no longer aborts publishing.
- Dashboard: telemetry files are ordered by name so a file removed mid-run cannot crash generation.
- Removed unused globals, an unused variable and an unused import.

#### V51.0 - 2026-11-19
- Expanded Live with recommended diagnostic checks and the latest daily timelapse/capture report.
- Added CPU, memory, disk and active-throttling history, source coverage and event markers to Trends.
- Added daily reliability reports, capture-completeness history and client-side CSV exports.
- Added a recent-frame Archive view and automatic dashboard refresh.
- Downsampled older capture telemetry while preserving the latest 24 hours at full resolution to bound memory use.
- Preserved camera-control behavior and telemetry-v4 58-field contract.

#### V50.3.5 - 2026-11-19
- Corrected Raspberry Pi throttling bit decoding and aligned daily timelapse updates with daily health reports.
- Validate persisted quality-state structure and isolate camera-restart failures from the capture loop.
- Corrected controller configuration fingerprint constants.
- Added a camera systemd unit for clean installs without overwriting an existing unit.

#### V50.3.4 - 2026-11-19
- Added a Trends panel comparing the last 24 hours of camera-mode time, capture counts, quality, sharpness, brightness, exposure and gain.
- Added recent mode transitions and sample-count cues; all summaries are observational and do not alter camera control.

#### V50.3.3 - 2026-11-19
- Moved native main-view radio controls outside the page container so CSS view selectors reveal the selected dashboard view.

#### V50.3.2 - 2026-11-19
- Made main dashboard navigation work through native radio controls and CSS, independently of JavaScript.
- Retained JavaScript updates for dashboard URLs and chart rendering when available.

#### V50.3.1 - 2026-11-19
- Fixed navigation by isolating main-view handlers from Trends period tabs.
- Made the dashboard template valid and navigable before data injection; the generator injects its JSON payload once into a non-executable data block.
- Kept V50.3 trend periods, process-memory graph and telemetry-v4 contract.

#### V50.3 - 2026-11-19
- Added camera process RSS memory history to Trends.
- Restored trend graphs for 7-day and 30-day periods as Trends subtabs, alongside 24 hours.
- Preserved camera-control behavior and telemetry-v4 58-field schema.

#### V50.2 - 2026-11-19
- Made Advanced a clearly named, visible dashboard view.
- Restored Raspberry Pi CPU, memory, process, storage and uptime statistics on Live.
- Preserved the Gallery-free interface and V50.1 reliability behavior.
- Kept camera-control behavior and telemetry-v4 58-field schema unchanged.

#### V50.1 - 2026-11-19
- Simplified the dashboard to Live, 24-hour Trends, Events and Advanced.
- Removed Gallery, 7/30-day and detailed Controller views without changing background image publication.
- Added clear capture/FTP/control/storage states, concise alerts and no-data handling.
- Restored an explicit Advanced navigation view and Raspberry Pi statistics on Live.
- Preserved camera-control behaviour and the telemetry-v4 58-field schema.

#### V50 - 2026-11-19
- Added explicit release configuration validation and removed embedded FTP credentials.
- Added telemetry row validation and a structured incident/audit history.
- Added bounded camera and FTP worker recovery safeguards.
- Added dashboard incident visibility and package integrity verification.
- Preserved camera-control behaviour and the telemetry-v4 58-field schema.

#### V49.11.2 - 2026-11-18
- Removed the undeclared pathlib.Path dependency from controller analytics retention.
- Added a defined, defensive dashboard fmtTime() formatter.
- Registered all seven dashboard navigation handlers before optional panel rendering.
- Isolated Controller panel rendering so it cannot disable navigation.
- Added retention execution and JavaScript runtime/navigation verifier gates.
- Normalised malformed release paths in documentation.
- Camera-control behaviour and telemetry-v4 58-field schema remain unchanged.

### V49.11.1 - 2026-11-18
- Fixed controller analytics NameError caused by undefined MIN_FREE_SPACE_GB.
- Added ANALYTICS_MIN_FREE_SPACE_GB = 5.0 as the explicit analytics storage threshold.
- Isolated controller analytics failures from the primary capture cycle.
- Added verifier regression checks for analytics summary creation and capture-cycle isolation.
- Camera-control behaviour and telemetry-v4 58-field schema remain unchanged.

### V49.11 - 2026-11-18
- Combined V49.10 Controller Analytics and V49.11 anomaly intelligence.
- Added 48-hour controller history, limit persistence, per-mode learning and transition events.
- Added configuration fingerprint, per-mode anomaly baselines and explainable camera-health score.
- Extended Controller dashboard with health, persistence, learning, events and anomaly panels.
- Camera-control behaviour and telemetry-v4 58-field schema remain unchanged.

### V49.9.1 - 2026-11-18
- Added a dedicated seventh Controller dashboard view and navigation target.
- Moved detailed controller observability out of the Live Health Checks card.
- Added controller state, learning, limit and current-decision panels.
- Fixed controller rendering to use the embedded D.controller payload.
- Added seven-view and controller-renderer verifier gates.
- Camera control and telemetry-v4 58-field schema remain unchanged.

## Change log

### V49.9 - 2026-11-18
- Fixed the V49.8.0 browser runtime regression caused by the missing `fmt()` dashboard value formatter.
- Restored navigation for 24 Hours, 7 Days, 30 Days, Gallery and Diagnostics.
- Restored rendering of the V49.8 Mode Effectiveness and Mode Separation panels.
- Added verifier assertions for the formatter and all six navigation targets.
- Camera-control behaviour, mode thresholds and telemetry-v4 58-field schema remain unchanged.

### V49.9 - 2026-11-18
- Added Mode Effectiveness analysis using real rolling 24-hour telemetry.
- Added per-mode duration and sample-count cards for DAY, TWILIGHT, LOW LIGHT and NIGHT.
- Added Mode Separation metrics for brightness, exposure, analogue gain and image quality.
- Added observational DISTINCT / REVIEW / NO DATA assessments.
- Added TWILIGHT versus LOW LIGHT evidence summary without changing control behaviour.
- Fixed independent Live and 24 Hours mode timeline render targets.
- Collapsed repeated mode samples into proportional timeline segments with time tooltips.
- Corrected series downsampling to retain the newest point.
- Camera control, thresholds and telemetry-v4 58-field schema remain unchanged.

# Change log
## V49.7.1 - 2026-11-17
- Approved mock-up Live-page geometry is the frozen visual baseline.
- Restored the approved mock-up UI as the dashboard visual source of truth.
- Added persistent operational health strip.
- Added real DAY/TWILIGHT/LOW LIGHT/NIGHT mode timeline from telemetry.
- Added separate diagnostics graphs, log exposure scaling, readable axes/ticks/legends and summary statistics.
- Added telemetry-enriched Gallery cards and filters.
- Renamed Settings to read-only Diagnostics and eliminated raw missing values.
- Preserved V49.5 exact-set Gallery reconciliation and FTP transactional publication.
- Corrected release identity across version, core, documentation and deployment scripts.
- Camera-control behaviour and telemetry-v4 58-field schema unchanged.
