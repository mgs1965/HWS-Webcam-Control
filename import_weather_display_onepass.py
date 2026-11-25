#!/usr/bin/env python3
import argparse,csv,json,os,tempfile
from datetime import datetime,timezone
from pathlib import Path
from weather_db import connect
from import_weather_display import flt,valid,ground_from_row,flags,F
VERSION='1.1.0';SOURCE=1
SQL='''INSERT INTO observation(timestamp_utc,timestamp_local,source_system_id,import_batch_id,source_resolution_minutes,temperature_c,humidity_percent,dew_point_c,pressure_hpa,wind_speed_mph,wind_gust_mph,wind_direction_deg,rain_interval_mm,heat_index_c,solar_radiation_wm2,uv_index,indoor_temperature_c,indoor_humidity_percent,ground_temperature_c,quality_flags) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(timestamp_utc) DO NOTHING'''
def atomic(p,o):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);fd,t=tempfile.mkstemp(prefix=p.name+'.',dir=p.parent,text=True)
 try:
  with os.fdopen(fd,'w') as f:json.dump(o,f,indent=2,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
  os.replace(t,p)
 finally:
  try:os.unlink(t)
  except:pass
def load(p):
 try:return json.loads(Path(p).read_text())
 except:return {}
def complete(c,y):return bool(c.execute("select 1 from import_batch where selection_start=? and selection_end=? and status='COMPLETE' and rows_inserted>0 limit 1",(f'{y}-01-01',f'{y}-12-31')).fetchone())
def start_batch(c,path,y):
 x=c.execute("insert into import_batch(source_system_id,source_path,selection_start,selection_end,started_at,status) values(?,?,?,?,?,?)",(SOURCE,str(path),f'{y}-01-01',f'{y}-12-31',datetime.now(timezone.utc).isoformat(),'RUNNING')).lastrowid;c.commit();return x
def main():
 p=argparse.ArgumentParser();p.add_argument('csv',type=Path);p.add_argument('database',type=Path);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--from-year',type=int,default=2011);p.add_argument('--to-year',type=int,default=2022);p.add_argument('--commit-rows',type=int,default=25000);p.add_argument('--resume',action='store_true');a=p.parse_args();c=connect(a.database);cp=load(a.checkpoint) if a.resume else {};done=set(cp.get('completed_years',[]));resume_epoch=cp.get('last_timestamp_utc');cur=bid=None;n=ins=rej=0;last=None;prev_daily=None
 def checkpoint(status='RUNNING'):
  atomic(a.checkpoint,{'version':VERSION,'status':status,'source':str(a.csv),'database':str(a.database),'completed_years':sorted(done),'current_year':cur,'last_timestamp_utc':last,'updated_at':datetime.now(timezone.utc).isoformat()})
 def finish():
  nonlocal cur,bid,n,ins,rej,last
  if cur is None:return
  c.execute("update import_batch set completed_at=?,rows_read=?,rows_inserted=?,rows_rejected=?,status='COMPLETE',last_timestamp_utc=? where id=?",(datetime.now(timezone.utc).isoformat(),n,ins,rej,last,bid));c.commit();done.add(cur);print(f'YEAR {cur} COMPLETE read={n:,} inserted={ins:,} rejected={rej:,}',flush=True);checkpoint()
 try:
  with a.csv.open(newline='',encoding='utf-8-sig') as f:
   for r in csv.DictReader(f):
    try:y=int(r['observed_at_local'][:4])
    except:continue
    if y<a.from_year:continue
    if y>a.to_year:break
    if y in done or complete(c,y):done.add(y);continue
    if cur!=y:
     finish();cur=y;bid=start_batch(c,a.csv,y);n=ins=rej=0;last=None;prev_daily=None
    try:epoch=int(datetime.fromisoformat(r['observed_at_utc']).timestamp())
    except:rej+=1;continue
    if resume_epoch is not None and epoch<=resume_epoch:continue
    v={o:valid(flt(r,s),F[s]) for o,s in [('temperature_c','temperature_c'),('humidity_percent','humidity_pct'),('dew_point_c','dew_point_c'),('pressure_hpa','pressure_hpa'),('wind_speed_mph','wind_speed_mph'),('wind_gust_mph','wind_gust_mph'),('wind_direction_deg','wind_direction_deg'),('heat_index_c','heat_index_c'),('solar_radiation_wm2','solar_radiation_wm2'),('uv_index','uv_index'),('indoor_temperature_c','indoor_temperature_c'),('indoor_humidity_percent','indoor_humidity_pct')]};daily=flt(r,'daily_rain_counter_mm');rain=None;q=flags(r,v)
    if prev_daily is not None and daily is not None:
     d=round(daily-prev_daily,3)
     if d>=0:rain=d
     elif daily<=1:q|=256;rain=max(daily,0)
     else:q|=512
    elif daily is not None:rain=0.0
    if daily is not None:prev_daily=daily
    row=(epoch,r['observed_at_local'],SOURCE,bid,int(float(r.get('source_resolution_minutes') or 1)),v['temperature_c'],v['humidity_percent'],v['dew_point_c'],v['pressure_hpa'],v['wind_speed_mph'],v['wind_gust_mph'],v['wind_direction_deg'],rain,v['heat_index_c'],v['solar_radiation_wm2'],v['uv_index'],v['indoor_temperature_c'],v['indoor_humidity_percent'],ground_from_row(r),q);n+=1;last=epoch
    before=c.total_changes;c.execute(SQL,row);ins+=c.total_changes-before
    if n%a.commit_rows==0:c.execute('update import_batch set rows_read=?,rows_inserted=?,rows_rejected=?,last_timestamp_utc=? where id=?',(n,ins,rej,last,bid));c.commit();checkpoint();print(f'{y}: {n:,} read {ins:,} inserted',flush=True)
  finish();checkpoint('COMPLETE');print('IMPORT COMPLETE',sorted(done))
 except BaseException as e:
  if bid:c.execute('update import_batch set rows_read=?,rows_inserted=?,rows_rejected=?,last_timestamp_utc=?,message=? where id=?',(n,ins,rej,last,str(e),bid));c.commit()
  checkpoint('INTERRUPTED');raise
 finally:c.close()
if __name__=='__main__':main()
