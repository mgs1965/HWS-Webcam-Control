## Harpenden Weather Station Change Log

## V45-TL8-M2.5 - 2026-11-11

Status: Testing

### CHG-007 - LOW LIGHT entry exposure-product floor

Classification: EXPOSURE CONTROL REFINEMENT

Changed modules:
- core.py: adds transient `low_light_entry_floor_product` shared state.
- modes.py: arms the floor only for TWILIGHT -> LOW LIGHT using the inherited exposure x analogue-gain product; clears it on other entries and when LOW LIGHT is exited.
- exposure.py: prevents normal LOW LIGHT control from reducing exposure product below the inherited floor while retaining upward control, rate limiting, ACK handling and highlight-protection authority.
- Release metadata, validation and manifest updated to V45-TL8-M2.5.

Safety behaviour:
- Not armed on startup directly into LOW LIGHT.
- Not armed for NIGHT -> LOW LIGHT at dawn.
- HIGHLIGHT PROTECTION may override the floor.
- Cleared on leaving LOW LIGHT.

### V45-TL8-M2.4 - 2026-11-11

Status: Testing

#### CHG-006 - Correct telemetry failure handling and retention parsing

Classification: DEFECT CORRECTION

Changed modules:
- publishing.py: schema-validation failure now returns `None` without mutating the shared counter; `capture_frame` remains the single owner of telemetry failure counting and audit emission.
- monitoring.py: telemetry retention now parses both `camera_telemetry_vN_YYYYMM.csv[.gz]` and legacy `camera_telemetry_YYYYMM.csv[.gz]` filenames, and validates the month.
- version.py, core.py, weather_camera.py, README.md, ARCHITECTURE.md and verify_m2.py: release identity and validation updated to V45-TL8-M2.4.
- manifest.json: function hashes regenerated for the corrected release.

Unchanged behaviour:
- Camera capture and controls
- Exposure controller thresholds
- Mode thresholds and hysteresis
- AWB learning and locking
- Image-quality algorithms
- TL8 segment, today and daily timelapse algorithms
- FTP behaviour
- Telemetry schema remains v2

## V45-TL8-M2.3 - 2026-11-11
Status: Testing

### CHG-005 - Startup runtime identity
Classification: OBSERVABILITY

Changed modules:
- `version.py`: release bumped to V45-TL8-M2.3.
- `core.py`: adds `platform` and `socket` imports and release string.
- `runtime.py`: logs Python version, hostname, PID and service start timestamp.

Startup examples:
- `[STARTUP] Python=3.x.x`
- `[STARTUP] Host=weathercamera`
- `[STARTUP] PID=1234`
- `[STARTUP] Started=2026-11-11T10:38:00+00:00`


## V45-TL8-M2.2 - 2026-11-11
Status: Testing

### CHG-004 - Release traceability and explicit telemetry schema filenames
Classification: STRUCTURAL

Changed modules:
- `version.py`: central release metadata and telemetry schema version.
- `core.py`: release string updated to M2.2; telemetry schema version centralised.
- `publishing.py`: filenames are now `camera_telemetry_v2_YYYYMM.csv`; mismatch inside an explicit v2 file is an error and the row is not appended.
- `runtime.py`: startup logging reports release and telemetry schema version.
- `loader.py`: loads `version.py` before `core.py`.
- `verify_m2.py`: extended release/schema validation.

Unchanged behaviour:
- Camera capture and controls
- Exposure controller thresholds
- Mode thresholds/hysteresis
- AWB learning/locking
- Image-quality algorithms
- TL8 segment/today/daily algorithms
- FTP behaviour

Migration:
- Rename legacy 29-field November telemetry to `camera_telemetry_v1_202611.csv`.
- Rename the validated 40-field `camera_telemetry_202611_schema2.csv` to `camera_telemetry_v2_202611.csv`.
