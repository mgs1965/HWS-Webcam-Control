# V45-TL8-M2.5 Architecture

| Module | Ownership |
|---|---|
| `version.py` | Release identity and telemetry schema version |
| `core.py` | Imports, configuration, logging, locks, queues and shared runtime state |
| `camera.py` | Picamera2, capture, conversion, JPEG and overlays |
| `modes.py` | Solar calculations, DAY/TWILIGHT/LOW LIGHT/NIGHT and hysteresis |
| `exposure.py` | Manual exposure, gain, AWB learning and ACK/reconciliation |
| `image_quality.py` | Metering, sharpness, quality, lens and NIGHT observability |
| `state.py` | Persistent controller/quality state and audit |
| `publishing.py` | Status, telemetry and FTP |
| `timelapse.py` | TL8 segments, manifests, partial/today/daily output |
| `monitoring.py` | Storage, CPU, anomaly summaries and housekeeping |
| `runtime.py` | Main loop, cadence, startup and shutdown |
| `loader.py` | Loads physical modules into the preserved shared runtime namespace |
