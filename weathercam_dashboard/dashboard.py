#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,ftplib,html,json,os,re,shutil,socket,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
V='50.3.1'; ROOT=Path(os.getenv('WEATHERCAM_ROOT','/mnt/weathercam')); OUT=Path(os.getenv('DASHBOARD_OUT',str(ROOT/'dashboard')))
IMG=Path(os.getenv('WEATHERCAM_LATEST_IMAGE',str(ROOT/'frames/latest.jpg'))); HD=Path(os.getenv('WEATHERCAM_HEALTH_DIR',str(ROOT/'telemetry/health'))); TD=Path(os.getenv('WEATHERCAM_TELEMETRY_DIR',str(ROOT/'logs'))); LD=Path(os.getenv('WEATHERCAM_LOG_DIR',str(ROOT/'logs')))
def dt(x):
 try:return datetime.fromisoformat(str(x).replace('Z','+00:00')).astimezone(timezone.utc)
 except:return None
def num(x):
 try:return float(re.sub(r'[^0-9.+-]','',str(x)))
 except:return None
def get(d,path,default=None):
 x=d
 for p in path.split('.'):
  if not isinstance(x,dict) or p not in x:return default
  x=x[p]
 return default if x in ('',None) else x
def jsonfile(p):
 try:return json.loads(p.read_text())
 except:return {}
def controller_analytics():
 p=ROOT/'logs/controller_analytics.json'
 try:return json.loads(p.read_text()) if p.exists() else {}
 except (OSError,json.JSONDecodeError):return {}
def controller_history(limit=10080):
 p=ROOT/'logs/controller_history.jsonl'
 if not p.exists():return []
 out=[]
 for line in p.read_text(errors='ignore').splitlines()[-limit:]:
  try:out.append(json.loads(line))
  except json.JSONDecodeError:pass
 return out
def controller_events(limit=200):
 p=ROOT/'logs/controller_events.jsonl'
 if not p.exists():return []
 out=[]
 for line in p.read_text(errors='ignore').splitlines()[-limit:]:
  try:out.append(json.loads(line))
  except json.JSONDecodeError:pass
 return out

def status():
 for p in [ROOT/'logs/camera_status.json',ROOT/'status.json',ROOT/'telemetry/status.json']:
  if p.exists():
   d=jsonfile(p)
   if d:d['_mtime']=datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat();return d
 return {}
def health(hours=720):
 cut=datetime.now(timezone.utc)-timedelta(hours=hours); out=[]
 for p in sorted(HD.glob('health_*.jsonl'))[-40:]:
  try:
   for line in p.read_text(errors='replace').splitlines():
    try:r=json.loads(line); t=dt(r.get('timestamp'))
    except:continue
    if t and t>=cut:r['_ts']=t;out.append(r)
  except OSError:pass
 return sorted(out,key=lambda r:r['_ts'])
def telemetry(hours=720):
 cut=datetime.now(timezone.utc)-timedelta(hours=hours); out=[]
 files=sorted(TD.glob('camera_telemetry_v4_*.csv'),key=lambda p:p.stat().st_mtime)[-3:]
 for p in files:
  try:
   with p.open(newline='',encoding='utf-8-sig',errors='replace') as f:
    for r in csv.DictReader(f):
     t=dt(r.get('capture_time') or r.get('timestamp'))
     if t and t>=cut:r['_ts']=t;out.append(r)
  except OSError:pass
 return sorted(out,key=lambda r:r['_ts'])[-70000:]
def series(rows,path,maxp=144,scale=1):
 a=[]
 for r in rows:
  v=num(get(r,path) if '.' in path else r.get(path));t=r.get('_ts')
  if v is not None and t:a.append([int(t.timestamp()*1000),round(v*scale,3)])
 if len(a)>maxp:
  last=a[-1];step=max(1,len(a)//maxp);a=a[::step]
  if a and a[-1]!=last:a.append(last)
  a=a[-maxp:]
 return a[-maxp:]
def mode_series(rows,maxp=720):
 pts=[]
 for r in rows:
  t=r.get('_ts') or dt(r.get('capture_time') or r.get('timestamp'));m=r.get('camera_mode') or r.get('mode')
  if t and m:pts.append([int(t.timestamp()*1000),str(m).upper()])
 if len(pts)>maxp:
  step=max(1,len(pts)//maxp);pts=pts[::step]
 return pts

def mode_effectiveness(rows,now):
 cut=now-timedelta(hours=24); samples=[]
 for r in rows:
  t=r.get('_ts');m=str(r.get('camera_mode') or r.get('mode') or '').upper()
  if t and t>=cut and m:
   samples.append((t,m,r))
 modes=['DAY','TWILIGHT','LOW LIGHT','NIGHT'];out={m:{'duration_seconds':0,'samples':0} for m in modes}
 fields={'brightness':'brightness_raw','exposure_ms':'exposure_ms','analogue_gain':'analogue_gain','digital_gain':'digital_gain','quality':'image_quality_score','sharpness':'sharpness_score','solar_elevation':'solar_elevation_deg'}
 vals={m:{k:[] for k in fields} for m in modes}
 for i,(t,m,r) in enumerate(samples):
  if m not in out:continue
  end=samples[i+1][0] if i+1<len(samples) else now
  out[m]['duration_seconds']+=max(0,min((end-t).total_seconds(),1800));out[m]['samples']+=1
  for k,src in fields.items():
   v=num(r.get(src))
   if v is not None:vals[m][k].append(v)
 for m in modes:
  for k,a in vals[m].items():out[m][k]=round(sum(a)/len(a),2) if a else None
  out[m]['duration_seconds']=round(out[m]['duration_seconds'])
 transitions=[]
 for t,m,r in samples:
  if not transitions or transitions[-1]['mode']!=m:transitions.append({'timestamp':t.isoformat(),'mode':m})
 for i,m in enumerate(modes):
  if out[m]['samples']==0:out[m]['assessment']='NO DATA'
  elif m in ('DAY','NIGHT'):out[m]['assessment']='DISTINCT'
  else:
   peers=[]
   for pm in modes:
    if pm!=m and out[pm]['exposure_ms'] is not None:peers.append(abs((out[m]['exposure_ms'] or 0)-out[pm]['exposure_ms']))
   out[m]['assessment']='DISTINCT' if peers and min(peers)>=5 else 'REVIEW'
 return {'window_hours':24,'modes':out,'transitions':transitions,'evidence':'COLLECT EVIDENCE' if len(transitions)<6 else 'EVALUATE','note':'Observational only; no camera-control behaviour changed.'}

def events():
 out=[]
 p=LD/'weather_camera.log'
 if not p.exists():return out
 try:lines=p.read_text(errors='replace').splitlines()[-2000:]
 except:return out
 for line in lines:
  if any(x in line for x in (' WARNING ',' ERROR ',' CRITICAL ','[FTP FAILURE]','[MODE CHANGE]','[DAILY HEALTH]')):
   level='CRITICAL' if (' ERROR ' in line or ' CRITICAL ' in line) else 'WARNING' if ' WARNING ' in line else 'INFO';out.append({'level':level,'message':line[-200:]})
 return out[-12:][::-1]
def incidents(limit=100):
 out=[]
 for p in sorted(LD.glob('camera_audit_*.jsonl'))[-7:]:
  try:
   for line in p.read_text(errors='replace').splitlines():
    try:r=json.loads(line)
    except json.JSONDecodeError:continue
    if r.get('severity') in ('WARNING','ERROR','CRITICAL'):
     out.append(r)
  except OSError:pass
 return sorted(out,key=lambda r:r.get('timestamp',''),reverse=True)[:limit]
def atomic(p,text):
 p.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix=p.name+'.',dir=p.parent)
 try:
  with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(text);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def copy(src,dst):
 if not src.exists():return False
 dst.parent.mkdir(parents=True,exist_ok=True);tmp=dst.with_suffix(dst.suffix+'.tmp')
 try:
  shutil.copy2(src,tmp);os.replace(tmp,dst);return True
 except (FileNotFoundError,OSError):
  try:
   if tmp.exists():tmp.unlink()
  except OSError:pass
  return False

def recent_gallery_images(limit=48):
 found=[]
 try: paths=(ROOT/'frames').glob('frame_*.jpg')
 except OSError:return []
 for item in paths:
  try:found.append((item.stat().st_mtime,item))
  except (FileNotFoundError,OSError):continue
 found.sort(key=lambda x:x[0],reverse=True)
 return [p for _,p in found[:limit]]

def seconds_since(value,now):
 stamp=dt(value);return None if stamp is None else max(0,int((now-stamp).total_seconds()))
def publish():
 host=os.getenv('DASHBOARD_FTP_HOST');user=os.getenv('DASHBOARD_FTP_USER');pw=os.getenv('DASHBOARD_FTP_PASSWORD');remote=os.getenv('DASHBOARD_FTP_DIR','/')
 if not all((host,user,pw)):return 'disabled'
 desired={p.name for p in (OUT/'gallery').glob('frame_*.jpg') if p.is_file()}
 cls=ftplib.FTP_TLS if os.getenv('DASHBOARD_FTP_TLS','0')!='0' else ftplib.FTP
 ftp=cls();ftp.connect(host,int(os.getenv('DASHBOARD_FTP_PORT','21')),timeout=45);ftp.login(user,pw)
 if isinstance(ftp,ftplib.FTP_TLS):ftp.prot_p()
 ftp.cwd(remote)
 def ensure_gallery():
  ftp.cwd(remote)
  try:ftp.mkd('gallery')
  except ftplib.error_perm:pass
  ftp.cwd('gallery')
 def atomic_send(local,name):
  tmp=name+'.uploading'
  with local.open('rb') as handle:ftp.storbinary('STOR '+tmp,handle)
  try:ftp.delete(name)
  except ftplib.error_perm:pass
  ftp.rename(tmp,name)
 # Stage and verify every required gallery image before making the page visible.
 ensure_gallery()
 for name in sorted(desired):atomic_send(OUT/'gallery'/name,name)
 remote_frames={Path(n).name for n in ftp.nlst() if Path(n).name.startswith('frame_') and Path(n).name.lower().endswith('.jpg')}
 missing=desired-remote_frames
 if missing:raise RuntimeError('Remote gallery verification failed; missing: '+', '.join(sorted(missing)[:10]))
 # Remove only obsolete weather-camera frames. Preserve unrelated site files.
 obsolete=remote_frames-desired
 deleted=0
 for name in sorted(obsolete):
  try:ftp.delete(name);deleted+=1
  except ftplib.error_perm:pass
 # Recheck exact desired set after reconciliation.
 remote_frames={Path(n).name for n in ftp.nlst() if Path(n).name.startswith('frame_') and Path(n).name.lower().endswith('.jpg')}
 if remote_frames!=desired:raise RuntimeError(f'Remote gallery mismatch: desired={len(desired)} remote={len(remote_frames)}')
 # Commit top-level assets in safe order; HTML is always last.
 ftp.cwd(remote)
 for name in ('latest.jpg','dashboard-data.json','dashboard.html'):
  local=OUT/name
  if local.is_file():atomic_send(local,name)
 ftp.quit()
 return {'state':'published','gallery_files':len(desired),'obsolete_deleted':deleted,'remote_verified':True}

def generate(upload=False):
 now=datetime.now(timezone.utc)
 status_data=status()
 health_rows=health()
 telemetry_rows=telemetry()
 incident_rows=incidents(50)
 log_events=events()
 latest=telemetry_rows[-1] if telemetry_rows else {}
 last_health=health_rows[-1] if health_rows else {}
 def first(*values):
  return next((value for value in values if value not in (None,'')),None)
 capture_text=first(status_data.get('capture_time'),status_data.get('last_capture_time'),latest.get('capture_time'))
 capture_time=dt(capture_text)
 capture_age=max(0,int((now-capture_time).total_seconds())) if capture_time else None
 upload_time=dt(status_data.get('ftp_last_success_time'))
 upload_age=max(0,int((now-upload_time).total_seconds())) if upload_time else None
 ftp_health=str(status_data.get('ftp_health_state') or 'UNKNOWN').upper()
 control_health=str(first(status_data.get('control_health'),latest.get('control_health'),'UNKNOWN')).upper()
 disk_free=num(first(get(last_health,'storage.free_space_gb'),status_data.get('free_space_gb')))
 cpu_temp=num(get(last_health,'system.cpu_temperature_c'))
 cpu_load=num(get(last_health,'system.cpu_load_percent'))
 memory_percent=num(get(last_health,'memory.used_percent'))
 disk_percent=num(get(last_health,'storage.used_percent'))
 rss_bytes=num(get(last_health,'memory.process_rss_bytes'))
 camera_state='UNKNOWN' if capture_age is None else 'CRITICAL' if capture_age>120 else 'WARNING' if capture_age>30 else 'HEALTHY'
 mode=first(status_data.get('camera_mode'),latest.get('camera_mode'),'UNKNOWN')
 metrics={
  'capture_age_seconds':capture_age,'capture_state':camera_state,'upload_age_seconds':upload_age,
  'ftp_health':ftp_health,'ftp_consecutive_failures':int(num(status_data.get('ftp_consecutive_failures')) or 0),
  'ftp_worker_alive':status_data.get('ftp_worker_alive'),'control_health':control_health,
  'exposure_ms':num(first(latest.get('exposure_ms'),num(status_data.get('exposure_seconds'))*1000 if num(status_data.get('exposure_seconds')) is not None else None)),
  'gain':num(first(latest.get('analogue_gain'),status_data.get('analogue_gain'))),
  'quality':num(first(latest.get('image_quality_score'),status_data.get('image_quality_score'))),
  'disk_free_gb':disk_free,'disk_percent':disk_percent,'cpu_temp_c':cpu_temp,
  'cpu_load_percent':cpu_load,'memory_percent':memory_percent,
  'process_rss_mb':rss_bytes/1048576 if rss_bytes is not None else None,
  'host_uptime_seconds':num(get(last_health,'system.host_uptime_seconds')),
  'restart_count':num(status_data.get('camera_restart_count')),
  'process_uptime_seconds':num(status_data.get('uptime_seconds')),
 }
 reasons=[]
 if camera_state=='UNKNOWN':reasons.append('No camera capture data')
 elif camera_state=='CRITICAL':reasons.append('Camera data is more than 2 minutes old')
 elif camera_state=='WARNING':reasons.append('Camera data is delayed')
 if ftp_health=='OUTAGE':reasons.append('FTP upload is unavailable')
 elif ftp_health in ('DEGRADED','RECOVERING'):reasons.append('FTP upload is degraded')
 if control_health in ('UNHEALTHY','FAILED'):reasons.append('Camera control is unhealthy')
 elif control_health=='DEGRADED':reasons.append('Camera control is degraded')
 if disk_free is not None and disk_free<2:reasons.append('Disk space is critically low')
 elif disk_free is not None and disk_free<5:reasons.append('Disk space is low')
 if cpu_temp is not None and cpu_temp>=80:reasons.append('CPU temperature is critical')
 elif cpu_temp is not None and cpu_temp>=70:reasons.append('CPU temperature is elevated')
 critical=(camera_state=='CRITICAL' or ftp_health=='OUTAGE'
           or control_health in ('UNHEALTHY','FAILED')
           or (disk_free is not None and disk_free<2)
           or (cpu_temp is not None and cpu_temp>=80))
 warning=bool(reasons)
 state='CRITICAL' if critical else 'NO DATA' if camera_state=='UNKNOWN' else 'WARNING' if warning else 'HEALTHY'
 if not reasons:reasons=['All monitored systems are healthy']
 chart_series={}
 for period,hours in (('24h',24),('7d',168),('30d',720)):
  trend_cutoff=now-timedelta(hours=hours)
  recent_telemetry=[row for row in telemetry_rows if row.get('_ts') and row['_ts']>=trend_cutoff]
  recent_health=[row for row in health_rows if row.get('_ts') and row['_ts']>=trend_cutoff]
  chart_series[period]={
   'brightness':series(recent_telemetry,'brightness_raw'),
   'quality':series(recent_telemetry,'image_quality_score'),
   'exposure':series(recent_telemetry,'exposure_ms'),
   'process_memory':series(recent_health,'memory.process_rss_bytes',scale=1/1048576),
  }
 copy(IMG,OUT/'latest.jpg')
 gallery_dir=OUT/'gallery'
 gallery_dir.mkdir(parents=True,exist_ok=True)
 desired_names={image.name for image in recent_gallery_images()}
 for old_file in gallery_dir.glob('frame_*.jpg'):
  if old_file.name not in desired_names:
   try:old_file.unlink()
   except OSError:pass
 for image in recent_gallery_images():
  copy(image,gallery_dir/image.name)
 events_payload=[]
 for item in incident_rows:
  events_payload.append({
   'time':item.get('timestamp'),'severity':item.get('severity','INFO'),
   'message':str(item.get('event_type') or item.get('message') or 'Operational event').replace('_',' '),
  })
 for item in log_events:
  events_payload.append({'time':item.get('time'),'severity':item.get('level','INFO'),'message':item.get('message','Operational event')})
 safe_config={
  'release':'V50.3.1','telemetry_schema':4,'dashboard_refresh_minutes':5,
  'capture_interval_seconds':10,'ftp_configured':bool(os.getenv('DASHBOARD_FTP_HOST')),
  'ftp_tls':os.getenv('DASHBOARD_FTP_TLS','0')!='0',
 }
 payload={
  'version':V,'generated':now.isoformat(),'capture_time':capture_text,
  'state':state,'reasons':reasons[:2],'mode':mode,'metrics':metrics,
  'series':chart_series,'events':events_payload,'hostname':socket.gethostname(),
  'counts':{'health':len(health_rows),'telemetry':len(telemetry_rows)},
  'config':safe_config,
 }
 template=(Path(__file__).resolve().parent/'templates/dashboard.html').read_text()
 if template.count('__DATA__') != 1:raise RuntimeError('Dashboard template must contain exactly one data placeholder')
 template=template.replace('__DATA__',json.dumps(payload,separators=(',',':')).replace('</','<\\/'),1)
 atomic(OUT/'dashboard.html',template)
 atomic(OUT/'dashboard-data.json',json.dumps(payload,indent=2))
 result=publish() if upload else 'generated'
 print(json.dumps({'result':result,'state':state,'mode':mode,'capture_age_seconds':capture_age,'health_records':len(health_rows),'telemetry_records':len(telemetry_rows)}))
def main():
 p=argparse.ArgumentParser();p.add_argument('--upload',action='store_true');p.add_argument('--version',action='version',version=V);a=p.parse_args();generate(a.upload)
if __name__=='__main__':main()
