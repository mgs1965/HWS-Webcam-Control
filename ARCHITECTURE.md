# V54.1 Architecture

## Runtime assembly

`weather_camera.py` calls `loader.load_runtime()`. The loader executes physical subsystem files in `MODULE_ORDER` into one shared namespace, preserving the application's shared mutable state model. `runtime.py` owns the clock-aligned capture loop, signal handling, worker startup and shutdown.

The capture loop coordinates camera acquisition, camera-mode and exposure control, image-quality analysis, state persistence, FTP upload queuing, timelapse work, housekeeping and system-health snapshots. Dashboard recommendations and charts are read-only; they do not influence camera behavior.

## Telemetry and health history

`publishing.py` writes camera status and monthly capture telemetry. Telemetry schema v4 remains an immutable 58-field contract. `monitoring.py` records hourly system-health snapshots under `/mnt/weathercam/telemetry/health`, including CPU, storage, memory, process RSS, service state and Pi throttling flags.

## Dashboard generation and publication

`weathercam_dashboard/dashboard.py` combines current status, system-health history, capture telemetry, daily health reports, timelapse files and operational events. `generate()` injects one JSON payload into `weathercam_dashboard/templates/dashboard.html`; it checks for exactly one `__DATA__` placeholder and escapes closing-script text. The dashboard publisher remains a lightweight oneshot job scheduled every five minutes.

The dashboard has Live, Trends, Events, Advanced, Reports and Archive views. Live includes a latest-image view, component health, recommended diagnostic checks and the latest daily timelapse report. Trends provides 24-hour, 7-day and 30-day image and Pi-health graphs, with event markers and per-chart sample/time coverage. Older capture telemetry is sampled at a fixed stride outside the latest 24 hours to retain a 30-day view without loading the complete high-frequency history into memory. Hourly health history remains unsampled. Reports show daily capture completeness and timelapse results with CSV export. Archive displays up to 48 recent retained frames. CSV exports are built client-side from the generated data.

The generator keeps numeric trend series bounded and publishes gallery images before the dashboard page. FTP reconciliation still preserves unrelated remote files and makes the HTML the final asset committed.

## Release and deployment

`version.py` is the release identity source for V54.1 and telemetry schema v4. `manifest.json` records the release baseline, package filename and file inventory. `verify_v54_1.py` checks the release identity, telemetry contract, dashboard payload structure and regression guards. The installer deploys to `/mnt/weathercam/app/releases/HarpendenWeatherCamera-V54.1`, records a rollback target, and installs the camera unit only when no existing unit is registered.
