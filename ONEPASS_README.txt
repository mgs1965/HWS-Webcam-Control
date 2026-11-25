V1.1 ONE-PASS PRODUCTION IMPORT

Create a fresh production DB, then run:
 ionice -c2 -n7 nice -n 15 python3 import_weather_display_onepass.py \
   /mnt/weathercam/WDExtract/2011_2022_normalised.csv \
   /mnt/weathercam/data/harpenden_weather.db \
   --checkpoint /mnt/weathercam/data/weather_import_checkpoint.json

Resume after interruption with the identical command plus --resume.
The CSV is read once. Each year is a separate audited batch and committed at its boundary.
Years already completed in import_batch are skipped. Progress is also committed every
25,000 selected rows. Historical soil wetness, soil temperature and greenhouse temperature
remain NULL; only the approved high-confidence fields are imported.
