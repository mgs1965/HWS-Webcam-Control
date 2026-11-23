#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,ftplib,json,math,os,re,shutil,socket,tempfile
from datetime import datetime,timedelta,timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo
V='55.5'; ROOT=Path(os.getenv('WEATHERCAM_ROOT','/mnt/weathercam')); OUT=Path(os.getenv('DASHBOARD_OUT',str(ROOT/'dashboard')))
IMG=Path(os.getenv('WEATHERCAM_LATEST_IMAGE',str(ROOT/'frames/latest.jpg'))); HD=Path(os.getenv('WEATHERCAM_HEALTH_DIR',str(ROOT/'telemetry/health'))); TD=Path(os.getenv('WEATHERCAM_TELEMETRY_DIR',str(ROOT/'logs'))); LD=Path(os.getenv('WEATHERCAM_LOG_DIR',str(ROOT/'logs')))
def envnum(name,default):
 try:
  value=float(os.getenv(name,''))
  return value if math.isfinite(value) else default
 except ValueError:return default
TH={
 'capture_warning_seconds':envnum('DASHBOARD_CAPTURE_WARNING_SECONDS',30),
 'capture_critical_seconds':envnum('DASHBOARD_CAPTURE_CRITICAL_SECONDS',120),
 'disk_free_warning_gb':envnum('DASHBOARD_DISK_FREE_WARNING_GB',10),
 'disk_free_critical_gb':envnum('DASHBOARD_DISK_FREE_CRITICAL_GB',2),
 'disk_used_warning_percent':envnum('DASHBOARD_DISK_USED_WARNING_PERCENT',85),
 'disk_used_critical_percent':envnum('DASHBOARD_DISK_USED_CRITICAL_PERCENT',95),
 'cpu_temp_warning_c':envnum('DASHBOARD_CPU_TEMP_WARNING_C',70),
 'cpu_temp_critical_c':envnum('DASHBOARD_CPU_TEMP_CRITICAL_C',80),
 'memory_warning_percent':envnum('DASHBOARD_MEMORY_WARNING_PERCENT',85),
 'memory_critical_percent':envnum('DASHBOARD_MEMORY_CRITICAL_PERCENT',95),
 'health_stale_seconds':envnum('DASHBOARD_HEALTH_STALE_SECONDS',7200),
 'dashboard_stale_minutes':envnum('DASHBOARD_STALE_MINUTES',15),
}
LATITUDE=envnum('DASHBOARD_LATITUDE',51.829105);LONGITUDE=envnum('DASHBOARD_LONGITUDE',-0.380987)
TIMELAPSE_PREVIEW_MAX_MB=envnum('DASHBOARD_TIMELAPSE_MAX_MB',150)
PREVIEW_NAME='latest_timelapse.mp4'
KEOGRAM_NAME='latest_keogram.png'
KEOGRAM_MAX_MB=2
def dt(x):
 try:return datetime.fromisoformat(str(x).replace('Z','+00:00')).astimezone(timezone.utc)
 except:return None
def num(x):
 try:
  value=float(re.sub(r'[^0-9.+-]','',str(x)))
  return value if math.isfinite(value) else None
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
def daily_health_reports(limit=30):
 out=[]
 for p in sorted(LD.glob('daily_health_*.json'))[-limit:]:
  try:
   row=json.loads(p.read_text(encoding='utf-8'))
  except (OSError,ValueError,json.JSONDecodeError):
   continue
  if isinstance(row,dict):
   stamp=dt(row.get('date'))
   if stamp:
    row['_ts']=stamp
    out.append(row)
 return sorted(out,key=lambda row:row['_ts'])[-limit:]
def latest_timelapse():
 found=[]
 for p in (ROOT/'timelapse').glob('timelapse_*.mp4'):
  try:
   stat=p.stat()
   found.append((stat.st_mtime,p,stat.st_size))
  except OSError:
   continue
 if not found:return None
 modified,path,size=max(found,key=lambda item:item[0])
 return {'filename':path.name,'modified':datetime.fromtimestamp(modified,timezone.utc).isoformat(),'size_bytes':size}
def telemetry(hours=720):
 now=datetime.now(timezone.utc); cut=now-timedelta(hours=hours); recent_cut=now-timedelta(hours=min(hours,24)); out=[];older_index=0
 files=sorted(TD.glob('camera_telemetry_v4_*.csv'),key=lambda p:p.name)[-3:]
 for p in files:
  try:
   with p.open(newline='',encoding='utf-8-sig',errors='replace') as f:
    for r in csv.DictReader(f):
     t=dt(r.get('capture_time') or r.get('timestamp'))
     if not t or t<cut:continue
     r['_ts']=t
     if t>=recent_cut or older_index%5==0:out.append(r)
     if t<recent_cut:older_index+=1
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
def sample_coverage(rows,path):
 samples=[r for r in rows if r.get('_ts') and num(get(r,path) if '.' in path else r.get(path)) is not None]
 return {'samples':len(samples),'first':samples[0]['_ts'].isoformat() if samples else None,'last':samples[-1]['_ts'].isoformat() if samples else None}
def mode_series(rows,maxp=720):
 pts=[]
 for r in rows:
  t=r.get('_ts') or dt(r.get('capture_time') or r.get('timestamp'));m=r.get('camera_mode') or r.get('mode')
  if t and m:pts.append([int(t.timestamp()*1000),str(m).upper()])
 if len(pts)>maxp:
  step=max(1,len(pts)//maxp);pts=pts[::step]
 return pts

def events():
 out=[]
 p=LD/'weather_camera.log'
 if not p.exists():return out
 try:lines=p.read_text(errors='replace').splitlines()[-2000:]
 except:return out
 for line in lines:
  if any(x in line for x in (' WARNING ',' ERROR ',' CRITICAL ','[FTP FAILURE]','[MODE TRANSITION]','[DAILY HEALTH]')):
   level='CRITICAL' if (' ERROR ' in line or ' CRITICAL ' in line) else 'WARNING' if ' WARNING ' in line else 'INFO';out.append({'time':line[:19].replace(' ','T') if re.match(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d',line) else None,'level':level,'message':line[-200:]})
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

def duration_text(seconds):
 seconds=int(seconds)
 if seconds%3600==0 and seconds>=3600:return f'{seconds//3600} hours'
 if seconds%60==0 and seconds>=60:return f'{seconds//60} minutes'
 return f'{seconds} seconds'
def sync_timelapse_preview(video):
 target=OUT/PREVIEW_NAME
 if not video or TIMELAPSE_PREVIEW_MAX_MB<=0 or video['size_bytes']>TIMELAPSE_PREVIEW_MAX_MB*1048576:
  try:target.unlink()
  except OSError:pass
  return None
 src=ROOT/'timelapse'/video['filename']
 try:
  if target.exists() and target.stat().st_size==video['size_bytes'] and int(target.stat().st_mtime)==int(src.stat().st_mtime):return PREVIEW_NAME
 except OSError:pass
 return PREVIEW_NAME if copy(src,target) else None
def sync_keogram():
 target=OUT/KEOGRAM_NAME
 files=sorted((ROOT/'keogram').glob('keogram_*.png'),key=lambda p:p.name)
 if not files or files[-1].stat().st_size>KEOGRAM_MAX_MB*1048576:
  try:target.unlink()
  except OSError:pass
  return None
 src=files[-1]
 try:
  if target.exists() and target.stat().st_size==src.stat().st_size and int(target.stat().st_mtime)==int(src.stat().st_mtime):return {'filename':KEOGRAM_NAME,'date':keogram_date(src)}
 except OSError:pass
 return {'filename':KEOGRAM_NAME,'date':keogram_date(src)} if copy(src,target) else None
def keogram_date(path):
 return datetime.strptime(path.stem[8:],'%Y%m%d').date().isoformat()
def seconds_since(value,now):
 stamp=dt(value);return None if stamp is None else max(0,int((now-stamp).total_seconds()))
def publish():
 host=os.getenv('DASHBOARD_FTP_HOST');user=os.getenv('DASHBOARD_FTP_USER');pw=os.getenv('DASHBOARD_FTP_PASSWORD');remote=os.getenv('DASHBOARD_FTP_DIR','/')
 if not all((host,user,pw)):return 'disabled'
 desired={p.name for p in (OUT/'gallery').glob('frame_*.jpg') if p.is_file()}
 cls=ftplib.FTP_TLS if os.getenv('DASHBOARD_FTP_TLS','0')!='0' else ftplib.FTP
 ftp=cls()
 try:
  return publish_with(ftp,host,user,pw,remote,desired)
 finally:
  try:ftp.close()
  except Exception:pass
def publish_with(ftp,host,user,pw,remote,desired):
 ftp.connect(host,int(os.getenv('DASHBOARD_FTP_PORT','21')),timeout=45);ftp.login(user,pw)
 if isinstance(ftp,ftplib.FTP_TLS):ftp.prot_p()
 ftp.cwd(remote)
 def remote_names():
  try:return ftp.nlst()
  except ftplib.error_perm as exc:
   if str(exc).startswith('550'):return []
   raise
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
 remote_frames={Path(n).name for n in remote_names() if Path(n).name.startswith('frame_') and Path(n).name.lower().endswith('.jpg')}
 missing=desired-remote_frames
 if missing:raise RuntimeError('Remote gallery verification failed; missing: '+', '.join(sorted(missing)[:10]))
 # Remove only obsolete weather-camera frames. Preserve unrelated site files.
 obsolete=remote_frames-desired
 deleted=0
 for name in sorted(obsolete):
  try:ftp.delete(name);deleted+=1
  except ftplib.error_perm:pass
 # Recheck exact desired set after reconciliation.
 remote_frames={Path(n).name for n in remote_names() if Path(n).name.startswith('frame_') and Path(n).name.lower().endswith('.jpg')}
 if remote_frames!=desired:raise RuntimeError(f'Remote gallery mismatch: desired={len(desired)} remote={len(remote_frames)}')
 ftp.cwd(remote)
 archive=OUT/'keograms'
 if archive.is_dir() and any(archive.glob('keogram_*.png')):
  try:ftp.mkd('keograms')
  except ftplib.error_perm:pass
  ftp.cwd('keograms')
  for local in sorted(archive.glob('keogram_*.png')):
   try:ftp.voidcmd('TYPE I');remote_size=ftp.size(local.name)
   except (ftplib.error_perm,ftplib.error_reply,AttributeError):remote_size=None
   if remote_size!=local.stat().st_size:atomic_send(local,local.name)
  ftp.cwd(remote)
 # Commit top-level assets in safe order; HTML is always last.
 ftp.cwd(remote)
 preview=OUT/PREVIEW_NAME
 if preview.is_file():
  try:ftp.voidcmd('TYPE I');remote_size=ftp.size(PREVIEW_NAME)
  except (ftplib.error_perm,ftplib.error_reply,AttributeError):remote_size=None
  if remote_size!=preview.stat().st_size:atomic_send(preview,PREVIEW_NAME)
 keogram=OUT/KEOGRAM_NAME
 if keogram.is_file():
  try:ftp.voidcmd('TYPE I');remote_size=ftp.size(KEOGRAM_NAME)
  except (ftplib.error_perm,ftplib.error_reply,AttributeError):remote_size=None
  if remote_size!=keogram.stat().st_size:atomic_send(keogram,KEOGRAM_NAME)
 for name in ('latest.jpg','dashboard-data.json')+SITE_ASSETS+SITE_EXTRAS+tuple(h for h,_ in SITE_PAGES)+tuple(SITE_DETAILS):
  local=OUT/name
  if local.is_file():atomic_send(local,name)
 if 'data.html' in {Path(n).name for n in remote_names()}:ftp.delete('data.html')
 ftp.quit()
 return {'state':'published','gallery_files':len(desired),'obsolete_deleted':deleted,'remote_verified':True}

def timelapse_library(limit=14):
 out=[]
 for kind,pattern,keep in (('daily','timelapse_*.mp4',limit),('weekly','weekly_timelapse_*.mp4',8),('monthly','monthly_timelapse_*.mp4',12)):
  for p in sorted((ROOT/'timelapse').glob(pattern),key=lambda p:p.name)[-keep:]:
   try:stat=p.stat()
   except OSError:continue
   out.append({'kind':kind,'name':p.name,'size_mb':round(stat.st_size/1048576,1),'modified':datetime.fromtimestamp(stat.st_mtime,timezone.utc).isoformat(),'uploaded':p.with_suffix('.uploaded').exists() or Path(str(p)+'.uploaded').exists()})
 return out
def sync_keogram_archive(limit=7):
 directory=OUT/'keograms';directory.mkdir(parents=True,exist_ok=True)
 files=sorted((ROOT/'keogram').glob('keogram_*.png'),key=lambda p:p.name)[-limit:];wanted=set();out=[]
 for src in files:
  try:
   if src.stat().st_size>KEOGRAM_MAX_MB*1048576:continue
  except OSError:continue
  target=directory/src.name
  if copy(src,target):wanted.add(src.name);out.append({'date':keogram_date(src),'src':'keograms/'+src.name})
 for old in directory.glob('keogram_*.png'):
  if old.name not in wanted:
   try:old.unlink()
   except OSError:pass
 return out
_PARTS=Path(__file__).resolve().parent
for _part in ('astronomy.py','analytics.py','station.py','insights.py','recommendations.py','forecast.py','extras.py'):
  exec(compile((_PARTS/_part).read_text(encoding='utf-8'),str(_PARTS/_part),'exec'),globals())
SITE_PAGES=(('indexnew.html','Home'),('console.html','Live'),('weather34.html','Console'),('graphs.html','Graphs'),('rainfall.html','Rainfall'),('wind.html','Wind'),('forecast.html','Forecast'),('webcam.html','Webcam'),('radar.html','Radar'),('records.html','Records'),('compare.html','Compare'),('almanac.html','Almanac'),('reports.html','Reports'),('news.html','News'),('donate.html','Donate'),('about.html','About'),('mobile.html','Mobile'),('health.html','HWS Health'))
SITE_DETAILS={'index.html':('Site Chooser','indexnew.html'),'station.html':('About','about.html'),'dashboard.html':('HWS Health','health.html'),'webcamhealth.html':('Webcam Health','health.html'),'mbhealth.html':('Meteobridge','health.html'),'pihealth.html':('Pi Health','health.html'),'satellite.html':('Satellite','radar.html')}
SITE_NAV='<nav class="hws-nav" aria-label="Main menu">'+''.join(f'<a class="s-btn" href="{h}">{t}</a>' for h,t in SITE_PAGES)+'</nav>'
HEALTH_VIEWS=(('live','Current'),('trends','Trends'),('events','Events'),('advanced','Advanced'),('reports','Reports'),('archive','Archive'),('weather','Weather'),('insights','Insights'))
HEALTH_PAGES=(('webcamhealth.html','Webcam Health'),('mbhealth.html','Meteobridge'),('pihealth.html','Pi Health'))
def health_navigation(name):
 dashboard=name in ('dashboard.html','health.html')
 views=''.join(f'<label class="health-tab" for="view-{key}">{label}</label>' if dashboard else f'<a class="health-tab" href="health.html#{key}">{label}</a>' for key,label in HEALTH_VIEWS)
 pages=''.join(f'<a class="health-tab" href="{href}"'+(' aria-current="page"' if href==name else '')+f'>{label}</a>' for href,label in HEALTH_PAGES)
 return '<nav id="viewNav" class="health-nav" aria-label="Dashboard views">'+views+pages+'</nav>'
SITE_EXTRAS=('share.png',)
SITE_ASSETS=('site.css','site.js','favicon.svg','favicon.png','logo.svg','logo.png','banner.jpg')
SITE_HEAD='<link rel="icon" href="favicon.png" type="image/png"><link rel="apple-touch-icon" href="logo.png"><link rel="stylesheet" href="site.css"><script src="site.js"></script></head>'
SITE_FOOT='<footer id="hws-foot"><p class="hws-disclaimer">This information is provided by a private automatic weather station.<br>Though we strive to achieve accurate reporting for our own use, it is important that you DO NOT depend <br>on the data provided here for any purpose.</p><p class="hws-disclaimer">If you have found this site useful please visit the <a href="donate.html">donation page</a>.</p><p>&copy; 2026 Mark Sanders &nbsp; <a href="mailto:info@harpendenweatherstation.co.uk">Contact Me</a></p></footer>'
def site_document(name,text):
 title,current=SITE_DETAILS.get(name,(dict(SITE_PAGES).get(name,'Home'),name))
 title='Harpenden Weather Station - '+title
 nav=SITE_NAV.replace(f'href="{current}"',f'href="{current}" aria-current="page"')
 text=text.replace('__NAV__',nav).replace('</head>',SITE_HEAD,1)
 text=re.sub(r'<title>.*?</title>','<title>'+escape(title)+'</title>',text,count=1,flags=re.S)
 text=re.sub(r'(<h1\b[^>]*>).*?(</h1>)',lambda m:m[1]+'<img class="hws-logo" src="logo.svg" alt="">'+escape(title)+m[2],text,count=1,flags=re.S)
 if name=='index.html':text=text.replace('</header>',nav+'</header>',1)
 if name in ('dashboard.html','health.html','webcamhealth.html','mbhealth.html','pihealth.html'):
  sub=health_navigation(name)
  if '__HEALTH_NAV__' in text:text=text.replace('__HEALTH_NAV__',sub,1)
  else:text=text.replace('</header>','</header>'+sub,1)
 return text.replace('</body>',SITE_FOOT+'</body>',1)
def month_start(now):
 return now.astimezone(ZoneInfo('Europe/London')).replace(day=1,hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
def generate(upload=False):
 now=datetime.now(timezone.utc)
 status_data=status()
 health_rows=health()
 telemetry_rows=telemetry()
 report_rows=daily_health_reports()
 incident_rows=incidents(50)
 log_events=events()
 latest=telemetry_rows[-1] if telemetry_rows else {}
 last_health=health_rows[-1] if health_rows else {}
 latest_report=report_rows[-1] if report_rows else {}
 latest_video=latest_timelapse()
 health_age=seconds_since(last_health.get('timestamp'),now) if last_health else None
 reported_health=str(last_health.get('overall_health') or 'UNKNOWN').upper()
 pi_flags=get(last_health,'system.pi_throttling')
 throttle_fields=('throttled_now','under_voltage_now','frequency_capped_now','soft_temperature_limit_now')
 throttling_active=any(pi_flags.get(flag) is True for flag in throttle_fields) if isinstance(pi_flags,dict) else None
 for row in health_rows:
  flags=get(row,'system.pi_throttling')
  row['_throttling_active']=int(any(flags.get(flag) is True for flag in throttle_fields)) if isinstance(flags,dict) else None
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
 capture_percent=num(latest_report.get('capture_completeness_percent'))
 camera_state='UNKNOWN' if capture_age is None else 'CRITICAL' if capture_age>TH['capture_critical_seconds'] else 'WARNING' if capture_age>TH['capture_warning_seconds'] else 'HEALTHY'
 mode=first(status_data.get('camera_mode'),latest.get('camera_mode'),'UNKNOWN')
 metrics={
  'capture_age_seconds':capture_age,'capture_state':camera_state,'upload_age_seconds':upload_age,
  'ftp_health':ftp_health,'ftp_consecutive_failures':int(num(status_data.get('ftp_consecutive_failures')) or 0),
  'ftp_worker_alive':status_data.get('ftp_worker_alive'),'ftp_outage_count':int(num(status_data.get('ftp_outage_count')) or 0),'ftp_recovery_count':int(num(status_data.get('ftp_recovery_count')) or 0),'control_health':control_health,
  'exposure_ms':num(first(latest.get('exposure_ms'),num(status_data.get('exposure_seconds'))*1000 if num(status_data.get('exposure_seconds')) is not None else None)),
  'gain':num(first(latest.get('analogue_gain'),status_data.get('analogue_gain'))),
  'quality':num(first(latest.get('image_quality_score'),status_data.get('image_quality_score'))),
  'disk_free_gb':disk_free,'disk_percent':disk_percent,'cpu_temp_c':cpu_temp,
  'cpu_load_percent':cpu_load,'memory_percent':memory_percent,
  'process_rss_mb':rss_bytes/1048576 if rss_bytes is not None else None,
  'host_uptime_seconds':num(get(last_health,'system.host_uptime_seconds')),
  'restart_count':num(status_data.get('camera_restart_count')),
  'process_uptime_seconds':num(status_data.get('uptime_seconds')),
  'capture_completeness_percent':capture_percent,
  'throttling_active':throttling_active,
  'throttling_value':num(get(last_health,'system.pi_throttling.value')),
  'health_age_seconds':health_age,
  'reported_health':reported_health,
 }
 reasons=[]
 if camera_state=='UNKNOWN':reasons.append('No camera capture data')
 elif camera_state=='CRITICAL':reasons.append(f"Camera data is more than {duration_text(TH['capture_critical_seconds'])} old")
 elif camera_state=='WARNING':reasons.append('Camera data is delayed')
 if ftp_health=='OUTAGE':reasons.append('FTP upload is unavailable')
 elif ftp_health in ('DEGRADED','RECOVERING'):reasons.append('FTP upload is degraded')
 if control_health in ('UNHEALTHY','FAILED'):reasons.append('Camera control is unhealthy')
 elif control_health=='DEGRADED':reasons.append('Camera control is degraded')
 if disk_free is not None and disk_free<TH['disk_free_critical_gb']:reasons.append('Disk space is critically low')
 elif disk_free is not None and disk_free<TH['disk_free_warning_gb']:reasons.append('Disk space is low')
 if cpu_temp is not None and cpu_temp>=TH['cpu_temp_critical_c']:reasons.append('CPU temperature is critical')
 elif cpu_temp is not None and cpu_temp>=TH['cpu_temp_warning_c']:reasons.append('CPU temperature is elevated')
 if memory_percent is not None and memory_percent>=TH['memory_critical_percent']:reasons.append('Memory usage is critical')
 elif memory_percent is not None and memory_percent>=TH['memory_warning_percent']:reasons.append('Memory usage is high')
 if disk_percent is not None and disk_percent>=TH['disk_used_critical_percent'] and (disk_free is None or disk_free>=TH['disk_free_critical_gb']):reasons.append('Disk usage is critical')
 elif disk_percent is not None and disk_percent>=TH['disk_used_warning_percent'] and (disk_free is None or disk_free>=TH['disk_free_warning_gb']):reasons.append('Disk usage is high')
 if throttling_active:reasons.append('Raspberry Pi throttling is active')
 health_reasons=get(last_health,'health_reasons',[])
 if isinstance(health_reasons,list):
  for reason in health_reasons:
   if isinstance(reason,str) and reason not in reasons:reasons.append(reason)
 if health_age is None or health_age>TH['health_stale_seconds']:reasons.append('Raspberry Pi health data is stale')
 elif reported_health=='CRITICAL' and not any('critical' in reason.lower() for reason in reasons):
  reasons.append('Raspberry Pi health snapshot reports a critical condition')
 critical=(camera_state=='CRITICAL' or ftp_health=='OUTAGE'
           or control_health in ('UNHEALTHY','FAILED')
           or (disk_free is not None and disk_free<TH['disk_free_critical_gb'])
           or (cpu_temp is not None and cpu_temp>=TH['cpu_temp_critical_c'])
           or (memory_percent is not None and memory_percent>=TH['memory_critical_percent'])
           or (disk_percent is not None and disk_percent>=TH['disk_used_critical_percent'])
           or (reported_health=='CRITICAL' and health_age is not None and health_age<=TH['health_stale_seconds'])
           or throttling_active is True)
 warning=bool(reasons)
 state='CRITICAL' if critical else 'NO DATA' if camera_state=='UNKNOWN' else 'WARNING' if warning else 'HEALTHY'
 urgent=('critical','unavailable','unhealthy','more than','throttling')
 reasons.sort(key=lambda reason:not any(word in reason.lower() for word in urgent))
 if not reasons:reasons=['All monitored systems are healthy']
 chart_series={};chart_coverage={};chart_modes={}
 report_rows=[row for row in report_rows if row.get('_ts') and row['_ts']>=now-timedelta(days=30)]
 report_series=[dict(row,capture_completeness_percent=num(row.get('capture_completeness_percent'))) for row in report_rows]
 series_sources={
  'brightness':('telemetry','brightness_raw',1),
  'quality':('telemetry','image_quality_score',1),
  'exposure':('telemetry','exposure_ms',1),
  'process_memory':('health','memory.process_rss_bytes',1/1048576),
  'cpu_temperature':('health','system.cpu_temperature_c',1),
  'cpu_load':('health','system.cpu_load_percent',1),
  'system_memory':('health','memory.used_percent',1),
  'disk_used':('health','storage.used_percent',1),
  'throttling':('health','_throttling_active',1),
  'gain':('telemetry','analogue_gain',1),
  'capture_completeness':('reports','capture_completeness_percent',1),
 }
 for period,hours in (('24h',24),('7d',168),('30d',720),('month',None)):
  trend_cutoff=month_start(now) if hours is None else now-timedelta(hours=hours)
  recent_telemetry=[row for row in telemetry_rows if row.get('_ts') and row['_ts']>=trend_cutoff]
  recent_health=[row for row in health_rows if row.get('_ts') and row['_ts']>=trend_cutoff]
  recent_reports=[row for row in report_series if row['_ts']>=trend_cutoff]
  sources={'telemetry':recent_telemetry,'health':recent_health,'reports':recent_reports}
  chart_series[period]={}
  chart_coverage[period]={}
  chart_modes[period]=mode_series(recent_telemetry)
  for key,(source,path,scale) in series_sources.items():
   rows=sources[source]
   chart_series[period][key]=series(rows,path,scale=scale)
   chart_coverage[period][key]=sample_coverage(rows,path)
 copy(IMG,OUT/'latest.jpg')
 gallery_dir=OUT/'gallery'
 gallery_dir.mkdir(parents=True,exist_ok=True)
 gallery_images=recent_gallery_images()
 desired_names={image.name for image in gallery_images}
 for old_file in gallery_dir.glob('frame_*.jpg'):
  if old_file.name not in desired_names:
   try:old_file.unlink()
   except OSError:pass
 gallery_items=[]
 for image in gallery_images:
  if not copy(image,gallery_dir/image.name):continue
  try:
   modified=datetime.fromtimestamp(image.stat().st_mtime,timezone.utc).isoformat()
   gallery_items.append({'src':'gallery/'+image.name,'captured':modified})
  except OSError:
   continue
 events_payload=[]
 for item in incident_rows:
  events_payload.append({
   'time':item.get('timestamp'),'severity':item.get('severity','INFO'),
   'message':str(item.get('event_type') or item.get('message') or 'Operational event').replace('_',' '),
  })
 for item in log_events:
  events_payload.append({'time':item.get('time'),'severity':item.get('level','INFO'),'message':item.get('message','Operational event')})
 wseries_all=weather_series(now)
 events_payload.extend(weather_events(wseries_all))
 scene_rows=scene_records(now,max(31,(now-month_start(now)).days+1))
 smart=smart_events(scene_rows,wseries_all,now)
 events_payload.extend(smart)
 daily_stats=update_daily_stats(LD/'dashboard_daily_stats.json',telemetry_rows,scene_rows,report_rows,now)
 insights={'quality_forecast':quality_forecast(telemetry_rows,now),'quality_explanation':quality_explanation(scene_rows,telemetry_rows,now),'lens_maintenance':lens_maintenance(scene_rows,telemetry_rows,now),'correlations':correlations(scene_rows,telemetry_rows,now),'daily_summaries':daily_summaries(telemetry_rows,scene_rows,report_rows,incident_rows,now),'long_term':long_term_report(daily_stats),'smart_events':smart[-10:]}
 timeline_events=[{
  'time':item.get('timestamp'),
  'severity':str(item.get('severity','INFO')).upper(),
  'message':str(item.get('event_type') or item.get('message') or 'Operational event').replace('_',' '),
 } for item in incident_rows if dt(item.get('timestamp'))]
 gap_details=latest_report.get('timelapse_source_gaps',[])
 if not isinstance(gap_details,list):gap_details=[]
 preview=sync_timelapse_preview(latest_video)
 timelapse={
  'report_date':latest_report.get('date'),
  'capture_count':num(latest_report.get('captures')),
  'captures_expected':num(latest_report.get('captures_expected')),
  'capture_completeness_percent':capture_percent,
  'local_complete':bool(latest_report.get('timelapse_local_complete')),
  'finalised':bool(latest_report.get('timelapse_publish_complete')),
  'build_method':latest_report.get('timelapse_build_method'),
  'segments':num(latest_report.get('timelapse_segments')),
  'expected_frames':num(latest_report.get('timelapse_expected_frames')),
  'source_gap_count':len(gap_details),
  'source_gaps':gap_details[:8],
  'latest_video':latest_video,'preview':preview,'preview_max_mb':TIMELAPSE_PREVIEW_MAX_MB,
  'latest_video_age_seconds':seconds_since(latest_video.get('modified'),now) if latest_video else None,
  'latest_video_size_mb':round(latest_video['size_bytes']/1048576,2) if latest_video else None,
 }
 daily_history=[{
  'date':row.get('date'),
  'captures':num(row.get('captures')),
  'captures_expected':num(row.get('captures_expected')),
  'capture_completeness_percent':num(row.get('capture_completeness_percent')),
  'health':row.get('overall'),
  'timelapse_local_complete':bool(row.get('timelapse_local_complete')),
 } for row in report_rows[-30:]]
 scene=status_data.get('scene') if isinstance(status_data.get('scene'),dict) else None
 weather=status_data.get('weather') if isinstance(status_data.get('weather'),dict) else None
 weather=weather_full(now,weather)
 station=station_status(now)
 actions=recommended_checks(metrics,timelapse,scene,station)
 wseries=weather_series(now);whour=weather_hour();whistory=weather_history();sc=solar_check(weather,scene,now)
 graphs=graph_data(now,wseries_all,scene_rows,daily_stats,whistory,weather_archive(),weather_local_daily())
 forecast=forecast_data(now);site=site_content()
 winsight=weather_insight(weather,scene)+frost_notes(weather)+record_notes(weather,whistory)+([sc['note']] if sc and sc.get('note') and sc.get('verdict')!='AGREE' else [])
 schedule=mode_schedule(now)
 safe_config={
  'release':'V55.5','telemetry_schema':4,'dashboard_refresh_minutes':5,'console_poll_seconds':30,
  'capture_interval_seconds':10,'ftp_configured':bool(os.getenv('DASHBOARD_FTP_HOST')),
  'ftp_tls':os.getenv('DASHBOARD_FTP_TLS','0')!='0',
  'thresholds':TH,'stale_after_minutes':TH['dashboard_stale_minutes'],'month_start':month_start(now).isoformat(),
 }
 payload={
  'version':V,'generated':now.isoformat(),'capture_time':capture_text,
  'state':state,'reasons':reasons[:2],'mode':mode,'metrics':metrics,
  'series':chart_series,'coverage':chart_coverage,'modes':chart_modes,'sun':sun_events(now),'quality_summary':quality_summary(telemetry_rows,now),'timeline_events':timeline_events,
  'mode_performance':mode_effectiveness(telemetry_rows,now),
  'sun_moon':sun_moon(now),'mode_schedule':schedule,'next_mode':next_mode_change(now,schedule),'calendar':day_calendar(report_rows),'timelapse_library':timelapse_library(),'keogram_archive':sync_keogram_archive(),'disk_forecast':disk_forecast(health_rows,now),
  'timelapse':timelapse,'recommendations':actions,'scene':scene,'periodic':status_data.get('periodic_timelapses') if isinstance(status_data.get('periodic_timelapses'),dict) else {},'weather':weather,'weather_history':whistory,'forecast':forecast,'weather_series':wseries,'weather_hour':whour,'wind_rose':wind_rose(wseries,whour),'weather_summary':weather_summary(wseries),'solar_check':solar_check(weather,scene,now),'scene_history':scene_history(now),'weather_insight':winsight,'keogram':sync_keogram(),
  'reports':{'latest':daily_history[-1] if daily_history else None,'history':daily_history},
  'gallery':gallery_items,
  'events':events_payload,'insights':insights,'station_status':station,'hostname':socket.gethostname(),
  'counts':{'health':len(health_rows),'telemetry':len(telemetry_rows)},
  'config':safe_config,
 }
 template=(Path(__file__).resolve().parent/'templates/dashboard.html').read_text()
 payload['meteobridge_health']=meteobridge_health(now,weather,station,graphs.get('daily') or [],weather_archive())
 if template.count('__DATA__') != 1:raise RuntimeError('Dashboard template must contain exactly one data placeholder')
 template=site_document('dashboard.html',template)
 template=template.replace('__DATA__',json.dumps(payload,separators=(',',':')).replace('</','<\\/'),1)
 atomic(OUT/'dashboard.html',template)
 atomic(OUT/'health.html',template)
 def page(name,data,out=None):
  text=site_document(out or name,(Path(__file__).resolve().parent/'templates'/name).read_text())
  atomic(OUT/(out or name),text.replace('__DATA__',json.dumps(data,separators=(',',':')).replace('</','<\\/'),1))
 for asset in SITE_ASSETS:
  src=Path(__file__).resolve().parent/'templates'/asset;dest=OUT/asset;dest.parent.mkdir(parents=True,exist_ok=True)
  tmp_asset=dest.with_name(dest.name+'.tmp');tmp_asset.write_bytes(src.read_bytes());os.replace(tmp_asset,dest)
 daily=graphs.get('daily') or []
 media=os.getenv('DASHBOARD_MEDIA_BASE','').strip();media=media+('/' if media and not media.endswith('/') else '')
 page('console.html',{k:payload.get(k) for k in ('weather','weather_series','weather_history','wind_rose','sun_moon','config')})
 page('weather34.html',{})
 page('graphs.html',{'graphs':graphs,'generated':now.isoformat()})
 page('forecast.html',{'forecast':forecast})
 page('mobile.html',{'weather':weather,'forecast':forecast})
 for kind in ('about','station'):page('info.html',{'kind':kind,'site':site,'weather':weather},kind+'.html')
 today=today_in_harpenden(now,daily);rose=wind_rose_periods(now,wseries_all,scene_rows);news=news_items(site)
 limits=alert_limits();alerts=weather_alerts(weather,limits)
 try:send_alerts(alerts,now,LD/'dashboard_alerts_state.json')
 except Exception as exc:print('[ALERTS] failed:',exc)
 try:share_card(weather,now,OUT/'share.png',Path(__file__).resolve().parent/'templates'/'logo.png')
 except Exception as exc:print('[SHARE CARD] failed:',exc)
 page('index.html',{})
 page('indexnew.html',{'alert_limits':limits,'today':today,'news':news[:3],'media_base':media,'keogram':payload.get('keogram'),'weather':weather,'forecast':forecast,'sun_moon':payload['sun_moon'],'weather_series':wseries,'site':site,'state':state,'capture_time':capture_text,'insights':winsight[:3]})
 page('webcam.html',{k:payload.get(k) for k in ('timelapse_library','keogram','keogram_archive','gallery','state','capture_time','mode')}|{'media_base':media})
 page('radar.html',{'site':site})
 page('satellite.html',{'site':site,'satellite':True})
 page('compare.html',{'daily':daily})
 page('rainfall.html',{'graphs':{k:graphs.get(k) for k in ('24h','7d','month','daily')},'generated':now.isoformat()})
 page('wind.html',{'rose':rose,'weather':weather,'generated':now.isoformat()})
 page('news.html',{'news':news})
 page('donate.html',{'paypal_button':os.environ.get('DASHBOARD_PAYPAL_BUTTON_ID','EX92D2ZBL7V3Y')})
 page('mbhealth.html',{'health':meteobridge_health(now,weather,station,daily,weather_archive()),'weather':weather,'weather_series':wseries,'graphs':graphs,'station_status':station,'generated':now.isoformat()})
 page('pihealth.html',{k:payload.get(k) for k in ('metrics','series','disk_forecast','hostname','version','generated','state')})
 page('records.html',{'legacy':LEGACY_RECORDS,'records':records_data(daily,now),'year_records':(whistory or {}).get('year_records')})
 page('reports.html',{'daily':daily})
 page('almanac.html',{'sun_moon':payload['sun_moon'],'almanac':almanac_data(now),'weather':weather,'scene':scene})
 page('health.html',{k:payload.get(k) for k in ('station_status','state','reasons','metrics','mode','capture_time','counts','generated','hostname','version')}|{'weather':weather},'webcamhealth.html')
 (OUT/'data.html').unlink(missing_ok=True)
 if os.environ.get('DASHBOARD_WRITE_REDIRECTS','').lower() in ('1','true','yes','on'):atomic(OUT/'redirects.htaccess',redirects_htaccess())
 atomic(OUT/'dashboard-data.json',json.dumps(payload,indent=2))
 result=publish() if upload else 'generated'
 print(json.dumps({'result':result,'state':state,'mode':mode,'capture_age_seconds':capture_age,'health_records':len(health_rows),'telemetry_records':len(telemetry_rows)}))
def main():
 p=argparse.ArgumentParser()
 p.add_argument('--upload',action='store_true')
 p.add_argument('--version',action='version',version=V)
 p.add_argument('--add-news',metavar='TITLE',help='save a news entry locally before generating the site')
 body=p.add_mutually_exclusive_group()
 body.add_argument('--news-text',metavar='TEXT')
 body.add_argument('--news-file',type=Path,help='UTF-8 text file containing the news entry')
 p.add_argument('--news-date',help='entry date in YYYY-MM-DD format (default today)')
 a=p.parse_args()
 if a.add_news:
  if not (a.news_text or a.news_file):p.error('--add-news requires --news-text or --news-file')
  if a.upload and not all(os.getenv(k) for k in ('DASHBOARD_FTP_HOST','DASHBOARD_FTP_USER','DASHBOARD_FTP_PASSWORD')):p.error('set DASHBOARD_FTP_HOST, DASHBOARD_FTP_USER and DASHBOARD_FTP_PASSWORD before uploading news')
  try:add_news(a.add_news,a.news_file.read_text(encoding='utf-8') if a.news_file else a.news_text,a.news_date)
  except (OSError,ValueError) as exc:p.error(str(exc))
 elif a.news_text or a.news_file or a.news_date:p.error('news options require --add-news')
 generate(a.upload)
if __name__=='__main__':main()
