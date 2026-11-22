# News, "today in Harpenden", wind rose and Meteobridge health helpers (included into dashboard.py).
WIND_CLASSES=((0.5,5),(5,10),(10,20),(20,None))
def news_items(site):
 """News entries: DASHBOARD_SITE_CONTENT entries first, then the bundled archive copied from the old site, newest first."""
 try:bundled=json.loads((Path(__file__).resolve().parent/'news_archive.json').read_text(encoding='utf-8'))
 except (OSError,ValueError):bundled=[]
 out=[];seen=set()
 for source in ((site or {}).get('news') or [],bundled if isinstance(bundled,list) else []):
  for n in source:
   if not isinstance(n,dict) or not isinstance(n.get('text'),str):continue
   item={'date':str(n.get('date',''))[:10],'time':str(n.get('time',''))[:5],'title':str(n.get('title',''))[:120],'text':n['text'][:4000]}
   key=(item['date'],item['title'])
   if key in seen:continue
   seen.add(key);out.append(item)
 return sorted(out,key=lambda n:(n['date'],n['time']),reverse=True)
def today_in_harpenden(now,daily):
 """Sunrise-to-sunset length and how it is changing, plus what happened on this date in earlier years."""
 out={'date':now.date().isoformat()}
 today=sun_times(now.date());yesterday=sun_times((now-timedelta(days=1)).date())
 if today:
  out['day_length_seconds']=int((today[1]-today[0]).total_seconds())
  if yesterday:out['day_length_change_seconds']=int((today[1]-today[0]).total_seconds()-(yesterday[1]-yesterday[0]).total_seconds())
 md=now.strftime('%m-%d');rows=[r for r in daily or [] if str(r.get('date',''))[5:10]==md and str(r.get('date',''))[:4]!=now.strftime('%Y')]
 out['years']=len(rows)
 for name,key,fn in (('hottest','temp_max_c',max),('coldest','temp_min_c',min),('wettest','rain_mm',max)):
  vals=[(num(r.get(key)),str(r['date'])[:4]) for r in rows if num(r.get(key)) is not None]
  if vals:
   best=fn(vals,key=lambda x:x[0])
   if name!='wettest' or best[0]>0:out[name]={'value':best[0],'year':best[1]}
 last=[r for r in rows if str(r['date'])[:4]==str(now.year-1)]
 if last:out['last_year']={k:num(last[0].get(k)) for k in ('temp_max_c','temp_min_c','rain_mm')}
 return out
def _rose(points):
 bins=[[0]*len(WIND_CLASSES) for _ in range(16)];calm=0;n=0
 for direction,speed in points:
  if direction is None or speed is None or not 0<=direction<=360:continue
  n+=1
  if speed<WIND_CLASSES[0][0]:calm+=1;continue
  for i,(lo,hi) in enumerate(WIND_CLASSES):
   if speed>=lo and (hi is None or speed<hi):bins[int(((direction%360)+11.25)//22.5)%16][i]+=1;break
 if n<6:return {}
 return {'samples':n,'calm_percent':round(100*calm/n,1),'percent':[[round(100*c/n,2) for c in row] for row in bins],'classes':[[lo,hi] for lo,hi in WIND_CLASSES]}
def wind_rose_periods(now,wseries,scene):
 """Wind rose for 24 h (weather station), 7 d and 30 d (camera scene log, which records wind direction from V54.3)."""
 out={'24h':_rose([(num(p.get('wind_direction_deg')),num(p.get('wind_speed_mph'))) for p in wseries or []])}
 for name,days in (('7d',7),('30d',30)):
  cut=now-timedelta(days=days);out[name]=_rose([(num(r.get('wind_direction_deg')),num(r.get('wind_speed_mph'))) for r in scene or [] if r.get('t') and r['t']>=cut])
 return {k:v for k,v in out.items() if v}
def meteobridge_health(now,weather,station,compare,daily,archive):
 """Checks on the Meteobridge link and on how complete the stored daily history is."""
 checks=[];w=weather or {};st=station or {}
 updated=dt(w.get('updated'));age=(now-updated).total_seconds() if updated else None
 checks.append({'name':'Latest reading','status':'unknown' if age is None else 'ok' if age<=600 else 'bad','detail':'No weather data yet' if age is None else f'{age/60:.0f} min old'})
 bridge=num(w.get('bridge_data_age_s'))
 checks.append({'name':'Console link','status':'unknown' if bridge is None else 'ok' if bridge<300 else 'warn' if bridge<600 else 'bad','detail':'Not reported' if bridge is None else f'Meteobridge data {bridge:.0f} s old'})
 rows=(compare or {}).get('rows') or []
 if rows:
  bad=[r['label'] for r in rows if r.get('status')=='differs']
  checks.append({'name':'Meteobridge vs clientraw','status':'warn' if bad else 'ok','detail':('Differ: '+', '.join(bad)) if bad else 'All values agree'})
 days={str(r.get('date'))[:10] for r in daily or [] if num(r.get('temp_max_c')) is not None or num(r.get('rain_mm')) is not None}
 today=now.date();gaps=[(today-timedelta(days=i)).isoformat() for i in range(1,31) if (today-timedelta(days=i)).isoformat() not in days]
 checks.append({'name':'Daily history (30 days)','status':'ok' if not gaps else 'warn' if len(gaps)<=3 else 'bad','detail':f'{30-len(gaps)} of 30 days stored'})
 arch=sorted(str(d)[:10] for d in (archive or {}))
 return {'checks':checks,'gaps':gaps[:10],'days_stored':len(days),'first_day':min(days) if days else None,'archive_days':len(arch),'archive_first':arch[0] if arch else None,'archive_last':arch[-1] if arch else None,'station_message':st.get('message')}
LEGACY_RECORDS=[
 {'label':'Lowest temperature','value':-11.9,'unit':'°C','date':'2012-02-11'},
 {'label':'Wettest day','value':68.1,'unit':'mm','date':'2021-06-18'},
 {'label':'Highest pressure','value':1048.1,'unit':'hPa','date':'2020-01-20'},
 {'label':'Lowest pressure','value':957.3,'unit':'hPa','date':'2023-11-02'}]

def alert_limits():
 """Alert thresholds, overridable with DASHBOARD_ALERT_FROST_C, _GUST_MPH and _RAIN_RATE_MM_H."""
 out={}
 for key,env,default in (('frost_c','DASHBOARD_ALERT_FROST_C',0.0),('gust_mph','DASHBOARD_ALERT_GUST_MPH',40.0),('rain_rate_mm_h','DASHBOARD_ALERT_RAIN_RATE_MM_H',10.0)):
  try:out[key]=float(os.environ.get(env,default))
  except ValueError:out[key]=default
 return out
def weather_alerts(weather,limits=None):
 """Active alerts for the current reading: frost, strong gusts and heavy rain."""
 w=weather or {};lim=limits or alert_limits();out=[]
 t=num(w.get('temperature_c'));g=num(w.get('wind_gust_mph'));r=num(w.get('rain_rate_mm_h'))
 if t is not None and t<=lim['frost_c']:out.append({'key':'frost','text':f'Frost: {t:.1f} °C at Harpenden'})
 if g is not None and g>=lim['gust_mph']:out.append({'key':'gust','text':f'Strong gusts: {g:.0f} mph at Harpenden'})
 if r is not None and r>=lim['rain_rate_mm_h']:out.append({'key':'rain','text':f'Heavy rain: {r:.1f} mm/h at Harpenden'})
 return out
def send_alerts(alerts,now,state_path,cooldown_hours=6):
 """Email (DASHBOARD_ALERT_SMTP_HOST/PORT/USER/PASSWORD/FROM/TO) and/or ntfy (DASHBOARD_ALERT_NTFY_URL) each new alert once per cooldown. Returns the keys sent."""
 smtp_host=os.environ.get('DASHBOARD_ALERT_SMTP_HOST','').strip();to=os.environ.get('DASHBOARD_ALERT_TO','').strip();ntfy=os.environ.get('DASHBOARD_ALERT_NTFY_URL','').strip()
 if not alerts or not ((smtp_host and to) or ntfy):return []
 try:state=json.loads(Path(state_path).read_text(encoding='utf-8'))
 except (OSError,ValueError):state={}
 if not isinstance(state,dict):state={}
 due=[]
 for a in alerts:
  last=dt(state.get(a['key']))
  if last is None or (now-last).total_seconds()>=cooldown_hours*3600:due.append(a)
 if not due:return []
 text='\n'.join(a['text'] for a in due);sent=False
 try:
  if smtp_host and to:
   import smtplib;from email.message import EmailMessage
   msg=EmailMessage();msg['Subject']='Weather alert: '+due[0]['text'];msg['From']=os.environ.get('DASHBOARD_ALERT_FROM',to);msg['To']=to;msg.set_content(text)
   with smtplib.SMTP(smtp_host,int(os.environ.get('DASHBOARD_ALERT_SMTP_PORT','587')),timeout=20) as server:
    server.starttls()
    if os.environ.get('DASHBOARD_ALERT_SMTP_USER'):server.login(os.environ['DASHBOARD_ALERT_SMTP_USER'],os.environ.get('DASHBOARD_ALERT_SMTP_PASSWORD',''))
    server.send_message(msg);sent=True
 except Exception as exc:print('[ALERTS] email failed:',exc)
 try:
  if ntfy:
   import urllib.request
   urllib.request.urlopen(urllib.request.Request(ntfy,data=text.encode('utf-8'),headers={'Title':'Harpenden weather alert'}),timeout=15).close();sent=True
 except Exception as exc:print('[ALERTS] ntfy failed:',exc)
 if sent:
  for a in due:state[a['key']]=now.isoformat()
  try:Path(state_path).write_text(json.dumps(state),encoding='utf-8')
  except OSError:pass
  return [a['key'] for a in due]
 return []
def share_card(weather,now,path,logo=None):
 """1200x630 PNG summary of the current weather for social media. Returns False if Pillow is unavailable."""
 try:from PIL import Image,ImageDraw,ImageFont
 except ImportError:return False
 w=weather or {}
 def font(size):
  for name in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','/Library/Fonts/Arial Bold.ttf','/System/Library/Fonts/Supplemental/Arial Bold.ttf'):
   try:return ImageFont.truetype(name,size)
   except OSError:pass
  try:return ImageFont.load_default(size)
  except TypeError:return ImageFont.load_default()
 img=Image.new('RGB',(1200,630),(4,38,26));d=ImageDraw.Draw(img);d.rectangle((0,0,1199,629),outline=(255,209,102),width=6)
 x=60
 if logo and Path(logo).is_file():
  try:
   badge=Image.open(logo).convert('RGBA').resize((150,150));img.paste(badge,(60,50),badge);x=240
  except Exception:pass
 def val(k,fmt,unit=''):
  v=num(w.get(k));return '–' if v is None else fmt.format(v)+unit
 d.text((x,60),'Harpenden Weather Station',font=font(46),fill=(255,209,102));d.text((x,125),now.strftime('%A %d %B %Y, %H:%M'),font=font(28),fill=(168,201,182))
 d.text((60,240),val('temperature_c','{:.1f}','°C'),font=font(130),fill=(238,247,240))
 rows=(('Humidity',val('humidity_percent','{:.0f}','%')),('Wind',val('wind_speed_mph','{:.0f}',' mph')+' '+compass_name(w.get('wind_direction_deg'))),('Gust',val('wind_gust_mph','{:.0f}',' mph')),('Pressure',val('pressure_hpa','{:.1f}',' hPa')),('Rain today',val('rain_today_mm','{:.1f}',' mm')))
 y=250
 for label,v in rows:
  d.text((560,y),label,font=font(30),fill=(168,201,182));d.text((800,y),v,font=font(34),fill=(238,247,240));y+=68
 d.text((60,560),'harpendenweatherstation.co.uk',font=font(28),fill=(168,201,182))
 tmp=Path(str(path)+'.tmp');img.save(tmp,format='PNG');os.replace(tmp,path);return True
def compass_name(deg):
 d=num(deg)
 return '' if d is None else ('N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW')[int((d%360)/22.5+0.5)%16]
