# Harpenden Weather Camera V45-TL8-M2.5

This is the physical modularisation of V45-TL8. The original monolithic Python file is not required at runtime.

## Architecture

- `core.py`: imports, constants, logging, locks, queues and shared state
- `camera.py`: Picamera2 setup, capture, conversion, overlay and recovery
- `modes.py`: Sun calculations, hysteresis and mode changes
- `exposure.py`: manual controller, AWB learning and control ACK handling
- `image_quality.py`: metering, quality, lens and NIGHT observability
- `state.py`: controller/quality persistence and audit
- `publishing.py`: status, telemetry and FTP
- `timelapse.py`: TL8 segments, manifests, today and daily videos
- `monitoring.py`: storage, CPU, anomaly reports and housekeeping
- `runtime.py`: signals, cadence and main loop
- `loader.py`: loads these physical modules into one shared namespace
- `weather_camera.py`: service entry point

The shared namespace is deliberate. It preserves V45-TL8's existing module-level mutable state, locks, queues and worker-thread semantics without retaining the monolith. A later M3 may replace this with explicit dataclass-based dependency injection after M2 has passed overnight regression testing.

## Install

Extract all files into one directory on the Raspberry Pi. Do not copy the old monolithic script into this directory. Preserve the existing service environment, including `HWS_FTP_PASSWORD`.

```bash
python3 verify_m2.py
python3 weather_camera.py
```

For systemd, change `ExecStart` to the absolute path of the new `weather_camera.py`, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl restart weather-camera
```

## Validation

First run for 10-15 minutes in parallel only if a second camera is available. Otherwise stop V45-TL8, start M2, and inspect startup/capture logs. Then run M2 through one dusk-to-dawn cycle and compare mode transitions, AWB lock, controller ACKs, anomaly summaries, hourly segments, today timelapse and FTP results with the validated 10th-11th baseline.

## Change tracking

Treat the complete module set as one release. Update `version.py`, record the change in `CHANGELOG.md`, run `verify_m2.py`, review `git diff`, then commit/tag the complete tested release.

Suggested initial Git commands:

```bash
git init
git add .
git commit -m "V45-TL8-M2.5 LOW LIGHT entry floor"
git tag -a V45-TL8-M2.5 -m "LOW LIGHT entry floor"
```

Telemetry v2 monthly files use `camera_telemetry_v2_YYYYMM.csv`.
