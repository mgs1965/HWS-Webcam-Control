# Function map

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
