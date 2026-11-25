HARPENDEN WEATHER SQLITE REPOSITORY v1.0.0
=========================================

PURPOSE
Creates a canonical SQLite repository and imports only the approved high-confidence
Weather Display fields. Historical soil wetness, soil temperature and greenhouse
temperature remain NULL. Ground/shielded temperature is imported only from verified
Extra Temp 1 keys. Meteobridge columns are reserved for later phases.

FILES
weather_schema.sql             Database schema
weather_db.py                  Creates/configures database
import_weather_display.py      Streaming, checkpointed CSV importer
build_daily_summaries.py       Builds daily summaries
verify_weather_db.py           Integrity/count/range checks
test_import.py                 Self-contained regression test

INSTALL
  mkdir -p /mnt/weathercam/WDRepository
  unzip harpenden_weather_sqlite_v1.0.0.zip -d /mnt/weathercam/WDRepository
  cd /mnt/weathercam/WDRepository
  python3 test_import.py

CREATE TEST DATABASE
  mkdir -p /mnt/weathercam/data
  python3 weather_db.py /mnt/weathercam/data/harpenden_weather-test.db

JANUARY 2012 DRY RUN
  python3 import_weather_display.py \
    /mnt/weathercam/WDExtract/2011_2022_normalised.csv \
    /mnt/weathercam/data/harpenden_weather-test.db \
    --from-date 2012-01-01 --to-date 2012-01-31 --dry-run --skip-sha256

JANUARY 2012 IMPORT
  python3 import_weather_display.py \
    /mnt/weathercam/WDExtract/2011_2022_normalised.csv \
    /mnt/weathercam/data/harpenden_weather-test.db \
    --from-date 2012-01-01 --to-date 2012-01-31 --skip-sha256

  python3 build_daily_summaries.py /mnt/weathercam/data/harpenden_weather-test.db
  python3 verify_weather_db.py /mnt/weathercam/data/harpenden_weather-test.db

Expected January row count from the prior extraction: 44,429.

FULL IMPORT
First create a fresh database. Import year by year; each run is a separately audited
batch and existing timestamps are ignored safely.

  for year in $(seq 2012 2022); do
    python3 import_weather_display.py \
      /mnt/weathercam/WDExtract/2011_2022_normalised.csv \
      /mnt/weathercam/data/harpenden_weather.db \
      --from-date ${year}-01-01 --to-date ${year}-12-31 --skip-sha256 || break
  done

Import December 2011 separately:
  python3 import_weather_display.py ... --from-date 2011-12-01 --to-date 2011-12-31 --skip-sha256

For provenance, calculate the 15 GB CSV checksum once outside each annual run:
  sha256sum /mnt/weathercam/WDExtract/2011_2022_normalised.csv
Store it alongside the migration records/report.

RESUME
The importer commits every 25,000 selected rows. If interrupted:
  python3 import_weather_display.py ...same dates... --resume --skip-sha256

SAFE IMPORT CONTRACT
Imported: timestamp, outdoor temperature/humidity/dew point/pressure, wind, reset-aware
interval rain, heat index, solar, UV, indoor temperature/humidity, verified Ground Temp.
Not populated from Weather Display: soil wetness, soil temperature, greenhouse temperature.

NOTES
- WAL mode is enabled.
- Invalid individual values become NULL with quality bits; the rest of the row remains.
- Source CSV is streamed, not loaded into RAM.
- ON CONFLICT DO NOTHING makes repeated year imports idempotent.
- Keep the current website and JSON feeds unchanged during this phase.
