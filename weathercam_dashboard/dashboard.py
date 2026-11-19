#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,ftplib,html,json,os,re,shutil,socket,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
V='49.11.2'; ROOT=Path(os.getenv('WEATHERCAM_ROOT','/mnt/weathercam')); OUT=Path(os.getenv('DASHBOARD_OUT',str(ROOT/'dashboard')))
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
 n=datetime.now(timezone.utc);s=status();h=health();t=telemetry(); ev=events(); ca=controller_analytics(); ch=controller_history(); ce=controller_events(); times=[]
 if h:times.append(h[-1]['_ts'])
 if t:times.append(t[-1]['_ts'])
 st=dt(s.get('capture_time') or s.get('last_capture_time') or s.get('timestamp') or s.get('_mtime'))
 if st:times.append(st)
 if IMG.exists():times.append(datetime.fromtimestamp(IMG.stat().st_mtime,timezone.utc))
 newest=max(times) if times else None; age=(n-newest).total_seconds()/60 if newest else None
 last=h[-1] if h else {}; metrics={'cpu_temp_c':num(get(last,'system.cpu_temperature_c')),'cpu_percent':num(get(last,'system.cpu_load_percent')),'memory_percent':num(get(last,'memory.used_percent')),'rss_mb':None,'disk_percent':num(get(last,'storage.used_percent'))}
 rb=num(get(last,'memory.process_rss_bytes')); metrics['rss_mb']=rb/1048576 if rb is not None else None
 mode=s.get('camera_mode') or s.get('mode') or (t[-1].get('camera_mode') if t else None) or get(last,'service.camera_mode') or 'UNKNOWN'
 reasons=[]
 if age is None or age>30:state='CRITICAL';reasons=['No fresh camera/status/telemetry data' if age is None else 'Data older than 30 minutes']
 elif age>10:state='WARNING';reasons=['Data older than 10 minutes']
 elif metrics['cpu_temp_c'] is not None and metrics['cpu_temp_c']>=80:state='CRITICAL';reasons=['CPU temperature critical']
 elif metrics['cpu_temp_c'] is not None and metrics['cpu_temp_c']>=70:state='WARNING';reasons=['CPU temperature elevated']
 else:state='HEALTHY';reasons=['All monitored systems nominal']
 ser={'cpuTemp':series(h,'system.cpu_temperature_c'),'cpu':series(h,'system.cpu_load_percent'),'memory':series(h,'memory.used_percent'),'rss':series(h,'memory.process_rss_bytes',scale=1/1048576),'quality':series(t,'image_quality_score'),'exposure':series(t,'exposure_ms'),'gain':series(t,'analogue_gain'),'digitalGain':series(t,'digital_gain'),'brightness':series(t,'brightness_raw'),'contrast':series(t,'contrast'),'highlights':series(t,'highlights_percent'),'sharpness':series(t,'sharpness_score'),'edgeDensity':series(t,'edge_density'),'processing':series(t,'capture_processing_ms'),'solarElevation':series(t,'solar_elevation_deg'),'modes':mode_series(t)}
 copy(IMG,OUT/'latest.jpg'); gallery_dir=OUT/'gallery';gallery_dir.mkdir(parents=True,exist_ok=True)
 desired_names={p.name for p in recent_gallery_images()}
 for old_file in gallery_dir.glob('frame_*.jpg'):
  if old_file.name not in desired_names:
   try:old_file.unlink()
   except OSError:pass
 published_local=[]
 for im in recent_gallery_images():
  if copy(im,OUT/'gallery'/im.name):published_local.append(im) 
 latest=t[-1] if t else {}
 def first(*vals): return next((v for v in vals if v not in (None,'')),None)
 def age_seconds(x):
  q=dt(x); return None if not q else max(0,int((n-q).total_seconds()))
 capture_age=age_seconds(first(s.get('capture_time'),s.get('last_capture_time'),latest.get('capture_time')))
 if capture_age is None and age is not None:capture_age=max(0,int(age*60))
 upload_age=age_seconds(first(s.get('ftp_last_success_time'),get(last,'ftp.last_success_time')))
 ftp_health=str(first(s.get('ftp_health_state'),get(last,'service.ftp_health'),'UNKNOWN')).upper()
 control_health=str(first(s.get('control_health'),latest.get('control_health'),get(last,'service.control_health'),'UNKNOWN')).upper()
 metrics.update({'capture_age_seconds':capture_age,'upload_age_seconds':upload_age,'exposure_ms':num(first(latest.get('exposure_ms'),num(s.get('exposure_seconds'))*1000 if num(s.get('exposure_seconds')) is not None else None)),'gain':num(first(latest.get('analogue_gain'),s.get('analogue_gain'))),'brightness':num(first(latest.get('brightness_filtered'),latest.get('brightness_raw'),s.get('filtered_brightness'))),'quality':num(first(latest.get('image_quality_score'),s.get('image_quality_score'))),'sharpness':num(first(latest.get('sharpness_score'),s.get('sharpness_score'))),'disk_free_gb':num(first(get(last,'storage.free_space_gb'),s.get('free_space_gb'))),'host_uptime_seconds':num(get(last,'system.host_uptime_seconds')),'process_uptime_seconds':num(first(get(last,'service.process_uptime_seconds'),s.get('uptime_seconds'))),'restart_count':num(first(get(last,'service.camera_restarts'),s.get('camera_restart_count'),0)),'ftp_health':ftp_health,'ftp_consecutive_failures':int(num(s.get('ftp_consecutive_failures')) or 0),'ftp_worker_alive':s.get('ftp_worker_alive'),'control_health':control_health})
 gallery=[]
 telemetry_by_time=[(r.get('_ts'),r) for r in t if r.get('_ts')]
 for im in published_local:
  try:
   its=datetime.fromtimestamp(im.stat().st_mtime,timezone.utc);nearest=min(telemetry_by_time,key=lambda x:abs((x[0]-its).total_seconds()))[1] if telemetry_by_time else {}
   gallery.append({'name':im.name,'time':its.isoformat(),'mode':nearest.get('camera_mode'),'quality':num(nearest.get('image_quality_score')),'brightness':num(nearest.get('brightness_raw')),'exposure_ms':num(nearest.get('exposure_ms')),'gain':num(nearest.get('analogue_gain'))})
  except (FileNotFoundError,OSError):continue
 safe_config={'release':'V49.11.2','telemetry_schema':4,'dashboard_refresh_minutes':5,'root':str(ROOT),'latest_image':str(IMG),'telemetry_dir':str(TD),'health_dir':str(HD),'ftp_configured':bool(os.getenv('DASHBOARD_FTP_HOST')),'ftp_tls':os.getenv('DASHBOARD_FTP_TLS','0')!='0','dashboard_output':str(OUT),'camera_status_file':str(ROOT/'logs/camera_status.json'),'gallery_items':len(gallery),'capture_interval_seconds':10,'frame_retention_days':7,'video_retention_days':30,'telemetry_retention_months':24,'image_resolution':'2560 x 1440','jpeg_quality':95}
 effect=mode_effectiveness(t,n)
 controller={k:s.get(k) for k in ('control_health','controller_decision','controller_target_brightness','controller_error','controller_deadband','controller_delta_ms','controller_delta_pct','controller_clamped_by','controller_next_exposure_ms','controller_at_exposure_limit','controller_at_gain_limit','learning_state','learning_mode','learning_samples_current','learning_samples_required','learning_progress_pct','software_version','telemetry_schema_version')}
 payload={'version':V,'generated':n.isoformat(),'state':state,'reasons':reasons,'mode':mode,'ageMinutes':None if age is None else round(age,1),'metrics':metrics,'series':ser,'modeEffectiveness':effect,'controller':controller,'controllerAnalytics':ca,'controllerHistory':ch,'controllerEvents':ce,'events':ev,'hostname':socket.gethostname(),'counts':{'health':len(h),'telemetry':len(t)},'gallery':gallery,'config':safe_config}
 tpl=(Path(__file__).resolve().parent/'templates/dashboard.html').read_text(); tpl=tpl.replace('__DATA__',json.dumps(payload,separators=(',',':')).replace('</','<\\/'))
 atomic(OUT/'dashboard.html',tpl);atomic(OUT/'dashboard-data.json',json.dumps(payload,indent=2)); result=publish() if upload else 'generated';print(json.dumps({'result':result,'state':state,'mode':mode,'age_minutes':payload['ageMinutes'],'health_records':len(h),'telemetry_records':len(t),'graph_points':{k:len(v) for k,v in ser.items()}}))
def main():
 p=argparse.ArgumentParser();p.add_argument('--upload',action='store_true');p.add_argument('--version',action='version',version=V);a=p.parse_args();generate(a.upload)
if __name__=='__main__':main()
