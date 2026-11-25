#!/usr/bin/env python3
"""Import high-confidence fields from v1.2 normalised Weather Display CSV."""
import argparse,csv,hashlib,json,sqlite3,time
from datetime import datetime,timezone
from pathlib import Path
from weather_db import connect
VERSION='1.0.0'; SOURCE=1
F={'temperature_c':(-40,55),'humidity_pct':(0,100),'dew_point_c':(-60,45),'pressure_hpa':(850,1100),'wind_speed_mph':(0,200),'wind_gust_mph':(0,250),'wind_direction_deg':(0,360),'heat_index_c':(-40,70),'solar_radiation_wm2':(0,2000),'uv_index':(0,30),'indoor_temperature_c':(-10,50),'indoor_humidity_pct':(0,100)}
def flt(row,key):
 s=row.get(key,'');
 try:return float(s) if s!='' else None
 except:return None
def valid(v,rng):return v if v is not None and rng[0]<=v<=rng[1] else None
def ground_from_row(row):
 direct=valid(flt(row,'ground_temperature_c'),(-40,60)) if 'ground_temperature_c' in row else None
 if direct is not None:return direct
 try:extra=json.loads(row.get('extra_measurements_json') or '{}')
 except (ValueError,TypeError):return None
 # Confirmed high-confidence WD Extra Temp 1 representations only.
 for key in ('raw_vantage_extra_sensors_temp1','raw_vantage_extra_sensors_temp_1','raw_extra_log_temp1','raw_extra_log_temp_1'):
  item=extra.get(key)
  value=item.get('value') if isinstance(item,dict) else item
  try:v=float(value)
  except (TypeError,ValueError):continue
  if v not in (-148,-100,255,1000,-1000,2550) and -40<=v<=60:return v
 return None
def sha256(path):
 h=hashlib.sha256();
 with path.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def flags(row,vals):
 q=0;s=row.get('quality_flags','')
 if flt(row,'humidity_pct') is not None and vals['humidity_percent'] is None:q|=1
 if flt(row,'pressure_hpa') is not None and vals['pressure_hpa'] is None:q|=2
 if flt(row,'dew_point_c') is not None and vals['dew_point_c'] is None:q|=4
 if flt(row,'temperature_c') is not None and vals['temperature_c'] is None:q|=8
 if 'INFO_WIND_EXCEEDS_REPORTED_GUST' in s or 'GUST_BELOW_WIND' in s:q|=16
 if 'FALLBACK' in s:q|=32
 if 'DUPLICATE' in s:q|=64
 if any(vals[k] is None for k in ('temperature_c','humidity_percent','pressure_hpa')):q|=128
 return q
def local_day(row):return row['observed_at_local'][:10]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('csv',type=Path);ap.add_argument('database',type=Path);ap.add_argument('--from-date');ap.add_argument('--to-date');ap.add_argument('--commit-rows',type=int,default=25000);ap.add_argument('--resume',action='store_true');ap.add_argument('--skip-sha256',action='store_true');ap.add_argument('--dry-run',action='store_true');a=ap.parse_args()
 c=connect(a.database);digest=None if a.skip_sha256 else sha256(a.csv);start=a.from_date;end=a.to_date
 batch=c.execute("SELECT id,last_timestamp_utc FROM import_batch WHERE source_path=? AND selection_start IS ? AND selection_end IS ? AND status='RUNNING' ORDER BY id DESC LIMIT 1",(str(a.csv),start,end)).fetchone() if a.resume else None
 if batch:bid,last=batch
 else:
  bid=c.execute("INSERT INTO import_batch(source_system_id,source_path,source_sha256,selection_start,selection_end,started_at,status) VALUES(?,?,?,?,?,?,?)",(SOURCE,str(a.csv),digest,start,end,datetime.now(timezone.utc).isoformat(),'RUNNING')).lastrowid;c.commit();last=None
 sql='''INSERT INTO observation(timestamp_utc,timestamp_local,source_system_id,import_batch_id,source_resolution_minutes,temperature_c,humidity_percent,dew_point_c,pressure_hpa,wind_speed_mph,wind_gust_mph,wind_direction_deg,rain_interval_mm,heat_index_c,solar_radiation_wm2,uv_index,indoor_temperature_c,indoor_humidity_percent,ground_temperature_c,quality_flags) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(timestamp_utc) DO NOTHING'''
 n=ins=rej=0;previous_daily=None;previous_monthly=None;previous_yearly=None
 try:
  with a.csv.open(newline='',encoding='utf-8-sig') as f:
   for row in csv.DictReader(f):
    day=local_day(row)
    if start and day<start:continue
    if end and day>end:continue
    try:dt=datetime.fromisoformat(row['observed_at_utc']);epoch=int(dt.timestamp())
    except:rej+=1;continue
    if last is not None and epoch<=last:continue
    vals={out:valid(flt(row,src),F[src]) for out,src in [('temperature_c','temperature_c'),('humidity_percent','humidity_pct'),('dew_point_c','dew_point_c'),('pressure_hpa','pressure_hpa'),('wind_speed_mph','wind_speed_mph'),('wind_gust_mph','wind_gust_mph'),('wind_direction_deg','wind_direction_deg'),('heat_index_c','heat_index_c'),('solar_radiation_wm2','solar_radiation_wm2'),('uv_index','uv_index'),('indoor_temperature_c','indoor_temperature_c'),('indoor_humidity_percent','indoor_humidity_pct')]}
    # Ground temperature is intentionally not decoded from verbose extra JSON here;
    # this conservative first import leaves it NULL unless a dedicated verified column exists.
    ground=ground_from_row(row)
    daily=flt(row,'daily_rain_counter_mm');monthly=flt(row,'monthly_rain_counter_mm');yearly=flt(row,'yearly_rain_counter_mm');rain=None;q=flags(row,vals)
    if previous_daily is not None and daily is not None:
     delta=round(daily-previous_daily,3)
     if delta>=0:rain=delta
     elif daily<=1.0:q|=256;rain=max(daily,0.0)
     else:q|=512
    elif daily is not None:rain=0.0
    if daily is not None:previous_daily=daily
    if monthly is not None:previous_monthly=monthly
    if yearly is not None:previous_yearly=yearly
    args=(epoch,row['observed_at_local'],SOURCE,bid,int(float(row.get('source_resolution_minutes') or 1)),vals['temperature_c'],vals['humidity_percent'],vals['dew_point_c'],vals['pressure_hpa'],vals['wind_speed_mph'],vals['wind_gust_mph'],vals['wind_direction_deg'],rain,vals['heat_index_c'],vals['solar_radiation_wm2'],vals['uv_index'],vals['indoor_temperature_c'],vals['indoor_humidity_percent'],ground,q)
    n+=1
    if not a.dry_run:
     before=c.total_changes;c.execute(sql,args);ins+=c.total_changes-before
     if n%a.commit_rows==0:c.execute('UPDATE import_batch SET rows_read=?,rows_inserted=?,rows_rejected=?,last_timestamp_utc=? WHERE id=?',(n,ins,rej,epoch,bid));c.commit();print(f'{n:,} read, {ins:,} inserted, {day}',flush=True)
  if a.dry_run:
   c.execute('DELETE FROM import_batch WHERE id=?',(bid,));c.commit();print(f'DRY RUN rows={n:,} rejected={rej:,}');return
  c.execute("UPDATE import_batch SET completed_at=?,rows_read=?,rows_inserted=?,rows_rejected=?,status='COMPLETE',last_timestamp_utc=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),n,ins,rej,epoch if n else last,bid));c.commit();print(f'COMPLETE rows={n:,} inserted={ins:,} rejected={rej:,} batch={bid}')
 except Exception as e:
  c.rollback();c.execute("UPDATE import_batch SET rows_read=?,rows_inserted=?,rows_rejected=?,status='RUNNING',message=? WHERE id=?",(n,ins,rej,str(e),bid));c.commit();raise
 finally:c.close()
if __name__=='__main__':main()
