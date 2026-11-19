# V50.3.1 Architecture

## Runtime assembly

`weather_camera.py` calls `loader.load_runtime()`. The loader executes the physical subsystem files in `MODULE_ORDER` into one shared namespace, preserving the application's shared mutable state model. `runtime.py` provides `main()` and owns the clock-aligned capture loop, signal handling, worker startup and shutdown.

The capture loop coordinates camera acquisition, camera-mode and exposure control, image-quality analysis, state persistence, FTP upload queuing, timelapse work, housekeeping and system-health snapshots. Camera, FTP, storage and processing failures are logged and handled within their owning subsystems so a recoverable capture-cycle error does not terminate the service.

## Telemetry and health history

`publishing.py` writes camera status and monthly telemetry. Telemetry schema v4 remains an immutable 58-field contract. `monitoring.py` records system-health snapshots in JSONL history under `/mnt/weathercam/telemetry/health`; snapshots include CPU, storage, memory and camera-process RSS measurements. Runtime startup forces an initial health snapshot, followed by snapshots at the configured interval.

## Dashboard generation and publication

`weathercam_dashboard/dashboard.py` combines the latest camera status with health history, telemetry CSV files and operational events. `generate()` builds the JSON payload and renders `weathercam_dashboard/templates/dashboard.html`; it checks for exactly one `__DATA__` placeholder and injects the payload once into a non-executable `application/json` block. The source template safely uses an empty payload when opened before generation, so its navigation remains functional.

The generator prepares brightness, image-quality and exposure series from telemetry and a process-memory series from health snapshots, each for 24-hour, 7-day and 30-day windows. It reduces chart series to a bounded number of points and converts process RSS to megabytes. `publish()` uploads the generated page and assets, including background Gallery images; the Gallery remains absent from the dashboard UI.

The dashboard exposes Live, Trends, Events and Advanced views. Trends period tabs are distinct from main-view navigation. The dashboard publisher is a oneshot systemd service, scheduled by `weathercam-dashboard.timer` every five minutes.

## Release and deployment

`version.py` is the release identity source for V50.3.1 and telemetry schema version 4. `manifest.json` records the release baseline, package filename and file inventory. The V50.3.1 verifier checks the release, telemetry contract, dashboard payload handling and navigation structure; the installer deploys to `/mnt/weathercam/app/releases/HarpendenWeatherCamera-V50.3.1` and records a rollback target.
