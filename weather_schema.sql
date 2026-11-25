PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
INSERT OR IGNORE INTO schema_version VALUES (1, datetime('now'));
CREATE TABLE IF NOT EXISTS source_system(id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, description TEXT);
INSERT OR IGNORE INTO source_system VALUES(1,'WEATHER_DISPLAY','Weather Display historical archive');
INSERT OR IGNORE INTO source_system VALUES(2,'METEOBRIDGE_IMPORTED','Meteobridge historical import');
INSERT OR IGNORE INTO source_system VALUES(3,'METEOBRIDGE_LIVE','Meteobridge live collection');
CREATE TABLE IF NOT EXISTS import_batch(
 id INTEGER PRIMARY KEY, source_system_id INTEGER NOT NULL REFERENCES source_system(id),
 source_path TEXT NOT NULL, source_sha256 TEXT, selection_start TEXT, selection_end TEXT,
 started_at TEXT NOT NULL, completed_at TEXT, rows_read INTEGER NOT NULL DEFAULT 0,
 rows_inserted INTEGER NOT NULL DEFAULT 0, rows_updated INTEGER NOT NULL DEFAULT 0,
 rows_rejected INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, last_timestamp_utc INTEGER,
 message TEXT
);
CREATE TABLE IF NOT EXISTS observation(
 timestamp_utc INTEGER PRIMARY KEY, timestamp_local TEXT NOT NULL,
 source_system_id INTEGER NOT NULL REFERENCES source_system(id), import_batch_id INTEGER REFERENCES import_batch(id),
 source_resolution_minutes INTEGER NOT NULL DEFAULT 1,
 temperature_c REAL, humidity_percent REAL, dew_point_c REAL, pressure_hpa REAL,
 wind_speed_mph REAL, wind_gust_mph REAL, wind_direction_deg REAL,
 rain_interval_mm REAL, heat_index_c REAL, solar_radiation_wm2 REAL, uv_index REAL,
 indoor_temperature_c REAL, indoor_humidity_percent REAL, ground_temperature_c REAL,
 soil_wetness_cbar REAL, soil_temperature_c REAL, greenhouse_temperature_c REAL,
 quality_flags INTEGER NOT NULL DEFAULT 0,
 CHECK(humidity_percent IS NULL OR humidity_percent BETWEEN 0 AND 100),
 CHECK(pressure_hpa IS NULL OR pressure_hpa BETWEEN 850 AND 1100),
 CHECK(wind_direction_deg IS NULL OR wind_direction_deg BETWEEN 0 AND 360),
 CHECK(rain_interval_mm IS NULL OR rain_interval_mm >= 0)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_observation_local ON observation(timestamp_local);
CREATE INDEX IF NOT EXISTS idx_observation_source ON observation(source_system_id,timestamp_utc);
CREATE TABLE IF NOT EXISTS quality_flag(bit INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, description TEXT NOT NULL);
INSERT OR IGNORE INTO quality_flag VALUES
 (1,'INVALID_HUMIDITY','Humidity rejected'),(2,'INVALID_PRESSURE','Pressure rejected'),
 (4,'INVALID_DEWPOINT','Dew point rejected'),(8,'SUSPECT_TEMPERATURE','Temperature rejected'),
 (16,'WIND_EXCEEDS_GUST','Wind exceeded reported gust'),(32,'FALLBACK_SOURCE','Fallback source used'),
 (64,'DUPLICATE_RESOLVED','Duplicate source was resolved'),(128,'PARTIAL_OBSERVATION','One or more values absent'),
 (256,'RAIN_COUNTER_RESET','Rain counter reset detected'),(512,'RAIN_UNRESOLVED','Rain interval could not be reconstructed');
CREATE TABLE IF NOT EXISTS daily_summary(
 day TEXT PRIMARY KEY, temperature_min REAL,temperature_max REAL,temperature_mean REAL,
 humidity_mean REAL,dew_point_mean REAL,pressure_min REAL,pressure_max REAL,pressure_mean REAL,
 rain_mm REAL,wind_gust_max_mph REAL,solar_max_wm2 REAL,uv_max REAL,
 ground_temperature_min REAL,ground_temperature_max REAL,ground_temperature_mean REAL,
 observation_count INTEGER NOT NULL,expected_observation_count INTEGER NOT NULL,
 completeness_pct REAL NOT NULL,quality_flags INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS repository_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID;
