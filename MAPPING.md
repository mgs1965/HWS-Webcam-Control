# Function map

Current release: V52.6. The dashboard template is rendered by `weathercam_dashboard/dashboard.py` and is not deployed with its `__DATA__` placeholder intact.

## camera.py
- `CameraAcquisitionError`
- `normalise_camera_array`
- `convert_array_to_image`
- `create_web_image`
- `load_overlay_font`
- `add_overlay`
- `save_jpeg_atomic`
- `replace_latest_image`
- `capture_frame`
- `restart_camera`

## scene_analysis.py
- Observational scene intelligence: `estimate_cloud_cover`, `estimate_fog_index`, `estimate_droplet_score`, `update_frozen_detection`, `update_blocked_detection`, `update_focus_drift`, `parse_weather_data`/`read_weather_data`, `update_scene_analysis`, `scene_overlay_texts`, `record_scene_history`, `cleanup_old_scene_history`.

## keogram.py
- Daily keogram: `record_keogram_slice` (called per capture), `render_keogram_image`, `finalise_keogram`, `process_pending_keograms`, `schedule_keogram_finalise`, `cleanup_old_keograms`.

## modes.py
- `local_now`
- `calculate_sun_time`
- `get_harpenden_sun_times`
- `calculate_solar_elevation`
- `determine_camera_mode`
- `maximum_exposure_for_mode`
- `configure_camera_mode`
- `check_for_new_day`

## exposure.py
- `clamp`
- `limited_change`
- `build_camera_controls`
- `update_awb_learning`
- `update_manual_exposure`

## image_quality.py
- `measure_image`
- `update_night_observability`
- `update_image_quality`

## state.py
- `snapshot_counters`
- `get_audit_log_filename`
- `audit_event`
- `cleanup_old_audit_logs`
- `save_quality_state`
- `load_quality_state`
- `save_controller_state`
- `load_controller_state`

## publishing.py
- `write_status_file`
- `get_monthly_telemetry_filename`
- `get_schema_safe_telemetry_filename`
- `append_monthly_telemetry`
- `connect_to_ftp`
- `upload_to_ftp`
- `remove_upload_snapshot`
- `cleanup_old_ftp_snapshots`
- `queue_live_upload`
- `ftp_worker`

## timelapse.py
- `unique_temporary_filename`
- `probe_video`
- `validate_timelapse`
- `frame_list_fingerprint`
- `get_day_frames`
- `get_hour_frames`
- `get_hourly_segment_directory`
- `get_segment_manifest_filename`
- `new_segment_manifest`
- `load_segment_manifest`
- `save_segment_manifest`
- `manifest_entry_matches`
- `record_segment_manifest`
- `remove_obsolete_partial`
- `_create_timelapse_from_frames_unlocked`
- `create_timelapse_from_frames`
- `build_hourly_segment`
- `build_partial_hour_segment`
- `_concatenate_video_segments_unlocked`
- `concatenate_video_segments`
- `collect_today_completed_segments`
- `process_hourly_today_timelapse`
- `schedule_hourly_today_timelapse`
- `collect_or_repair_daily_segments`
- `create_timelapse`
- `process_timelapse`
- `schedule_timelapse`

- Weekly/monthly summary videos: `periodic_period`, `build_periodic_timelapse`, `process_periodic_timelapses`, `schedule_periodic_timelapses`.

## monitoring.py
- `validate_storage_paths`
- `get_free_space_gb`
- `get_cpu_temperature_c`
- `cleanup_incomplete_timelapse_files`
- `compress_previous_month_telemetry`
- `cleanup_expired_telemetry`
- `emergency_storage_cleanup`
- `write_daily_health_summary`
- `update_daily_summary_timelapse_status`
- `cleanup_old_hourly_segments`
- `initialise_anomaly_window`
- `record_capture_anomalies`
- `log_anomaly_summary`
- `cleanup_old_files`

## runtime.py
- `handle_termination_signal`
- `install_signal_handlers`
- `sleep_until_next_capture`
- `main`

## weathercam_dashboard/dashboard.py
- `dt`
- `num`
- `get`
- `jsonfile`
- `controller_analytics`
- `controller_history`
- `controller_events`
- `status`
- `health`
- `daily_health_reports`
- `latest_timelapse`
- `recommended_checks`
- `telemetry`
- `series`
- `sample_coverage`
- `mode_series`
- `mode_effectiveness`
- `events`
- `incidents`
- `atomic`
- `copy`
- `recent_gallery_images`
- `seconds_since`
- `publish`
- `generate`
- `main`

`generate` assembles status, health, telemetry, daily reports, timelapse and event data into the dashboard payload. It prepares bounded 24-hour/7-day/30-day series, health recommendations, sample coverage, chart event markers, recent archive thumbnails and daily capture-completeness summaries. The most recent 24 hours of telemetry remain full resolution; older 30-day history is sampled. The payload is injected exactly once into the template's JSON data block. `publish` uploads the generated page and its assets.

## weathercam_dashboard/templates/dashboard.html
- Renders Live, Trends, Events, Advanced, Reports and Archive views.
- Trends period subtabs select 24-hour, 7-day and 30-day charts for image metrics, process memory, CPU, system memory, disk use and Pi throttling.
- Charts show their source sample count and time span, and annotate warning/error events.
- Trends compares 24-hour camera-mode capture counts, estimated time, descriptive telemetry averages and recent transitions; low sample counts are flagged.
- Reports show daily capture completeness and timelapse results with CSV export.
- Archive shows up to 48 recent retained camera frames.
- Trend and report CSV exports are generated in the browser from the dashboard payload.
- Main-view navigation uses native radio controls and CSS; Trends period controls are separate.
- Reads dashboard data from the `dashboard-data` JSON block; the source template remains navigable before data injection.

## Release and package files
- `version.py` contains the V52.6 release identity and telemetry schema version.
- `manifest.json` records the release baseline, package filename and release file inventory.
- `verify_v52_6.py` validates release identity, telemetry contract, dashboard structure and release guards.
- `test_v52_6.py` contains focused dashboard-data and runtime regression checks.
- `install_v52_6.sh` installs the release; `rollback_v52_6.sh` restores its recorded previous target.
- `build_release.py` builds `HWS-Webcam-Control-<version>.zip` (top-level directory `HWS-Webcam-Control-<version>/`) from `manifest.json`.
- `systemd/weathercam.service` provides the camera runtime unit on clean installs; the installer leaves an existing unit untouched.
