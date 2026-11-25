#!/usr/bin/env python3
import csv,json,sqlite3,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).parent
with tempfile.TemporaryDirectory() as td:
 t=Path(td);db=t/'w.db';src=t/'x.csv'
 fields=['observed_at_local','observed_at_utc','source_resolution_minutes','temperature_c','humidity_pct','dew_point_c','pressure_hpa','wind_speed_mph','wind_gust_mph','wind_direction_deg','daily_rain_counter_mm','monthly_rain_counter_mm','yearly_rain_counter_mm','heat_index_c','solar_radiation_wm2','uv_index','indoor_temperature_c','indoor_humidity_pct','extra_measurements_json','quality_flags']
 rows=[
 ['2012-01-01T00:00','2012-01-01T00:00+00:00','1','5','90','3.5','1010','2','4','180','0','0','0','5','0','0','18','60',json.dumps({'raw_vantage_extra_sensors_temp1':{'value':7.2}}),''],
 ['2012-01-01T00:01','2012-01-01T00:01+00:00','1','5.1','91','3.7','1010.1','2','4','181','0.2','0.2','0.2','5.1','0','0','18','60',json.dumps({'raw_vantage_extra_sensors_temp1':{'value':7.3}}),''],
 ['2012-01-02T00:00','2012-01-02T00:00+00:00','1','4','0','50','0','1','0.5','190','0','0.2','0.2','4','0','0','','',json.dumps({'raw_vantage_extra_sensors_temp1':{'value':255}}),'INFO_WIND_EXCEEDS_REPORTED_GUST'],
 ]
 with src.open('w',newline='') as f:w=csv.writer(f);w.writerow(fields);w.writerows(rows)
 subprocess.run(['python3',str(ROOT/'weather_db.py'),str(db)],check=True)
 subprocess.run(['python3',str(ROOT/'import_weather_display.py'),str(src),str(db),'--skip-sha256'],check=True)
 c=sqlite3.connect(db);a=c.execute('select count(*),sum(rain_interval_mm) from observation').fetchone();assert a==(3,0.2),a
 r=c.execute('select ground_temperature_c from observation order by timestamp_utc').fetchall();assert r==[(7.2,),(7.3,),(None,)],r
 q=c.execute('select humidity_percent,pressure_hpa,dew_point_c,quality_flags from observation order by timestamp_utc desc limit 1').fetchone();assert q[1] is None and q[2] is None and q[3]&2 and q[3]&4,q
 print('PASS',a,r,q)
