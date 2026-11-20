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
