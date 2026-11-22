# Forecast and static-site helpers (included into dashboard.py).
FORECAST_URL='https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat:.4f}&lon={lon:.4f}'
FORECAST_ENABLED=os.getenv('DASHBOARD_FORECAST','1')!='0'
FORECAST_REFRESH_SECONDS=envnum('DASHBOARD_FORECAST_REFRESH_MINUTES',60)*60
def _forecast_parse(doc,tz):
 """Reduce a MET Norway locationforecast document to hourly steps and per-day summaries."""
 hourly=[];days={}
 for step in ((doc.get('properties') or {}).get('timeseries') or []):
  try:t=datetime.fromisoformat(str(step['time']).replace('Z','+00:00')).astimezone(timezone.utc)
  except (KeyError,ValueError):continue
  data=step.get('data') or {};inst=(data.get('instant') or {}).get('details') or {}
  one=data.get('next_1_hours') or {};six=data.get('next_6_hours') or {}
  window=one or six;hours=1 if one else 6
  symbol=((window.get('summary') or {}).get('symbol_code')) or ((six.get('summary') or {}).get('symbol_code'))
  rain=num((window.get('details') or {}).get('precipitation_amount'))
  wind=num(inst.get('wind_speed'))
  row={'t':t.isoformat(),'temperature_c':num(inst.get('air_temperature')),'humidity_percent':num(inst.get('relative_humidity')),'pressure_hpa':num(inst.get('air_pressure_at_sea_level')),'cloud_pct':num(inst.get('cloud_area_fraction')),'wind_mph':None if wind is None else round(wind*2.23694,1),'wind_direction_deg':num(inst.get('wind_from_direction')),'rain_mm':rain,'hours':hours,'symbol':symbol}
  hourly.append(row)
  day=days.setdefault(t.astimezone(tz).date().isoformat(),{'temps':[],'rain':0.0,'rain_seen':False,'symbols':[],'wind':[]})
  if row['temperature_c'] is not None:day['temps'].append(row['temperature_c'])
  if rain is not None:day['rain']+=rain;day['rain_seen']=True
  if wind is not None:day['wind'].append(row['wind_mph'])
  if symbol:day['symbols'].append((abs(t.astimezone(tz).hour-13),symbol))
 daily=[{'date':d,'temp_max_c':round(max(v['temps']),1),'temp_min_c':round(min(v['temps']),1),'rain_mm':round(v['rain'],1) if v['rain_seen'] else None,'wind_max_mph':max(v['wind']) if v['wind'] else None,'symbol':min(v['symbols'])[1] if v['symbols'] else None} for d,v in sorted(days.items()) if v['temps']]
 return hourly,daily
def forecast_data(now):
 """Forecast from MET Norway (the data behind yr.no), cached on disk; falls back to the last good copy for up to 12 hours."""
 if not FORECAST_ENABLED:return None
 path=LD/'dashboard_forecast.json'
 try:cached=json.loads(path.read_text())
 except (OSError,ValueError):cached=None
 cached=cached if isinstance(cached,dict) and cached.get('hourly') else None
 fetched=None
 if cached:
  try:fetched=datetime.fromisoformat(cached['fetched'])
  except (KeyError,ValueError):fetched=None
 if cached and fetched and 0<=(now-fetched).total_seconds()<FORECAST_REFRESH_SECONDS:return cached
 try:
  import urllib.request
  req=urllib.request.Request(FORECAST_URL.format(lat=LATITUDE,lon=LONGITUDE),headers={'User-Agent':'HWS-Webcam-Control/'+V+' github.com/mgs1965/HWS-Webcam-Control'})
  with urllib.request.urlopen(req,timeout=15) as response:doc=json.loads(response.read().decode('utf-8'))
  hourly,daily=_forecast_parse(doc,now.astimezone().tzinfo)
  if not hourly:raise ValueError('empty forecast')
  fresh={'fetched':now.isoformat(),'source':'MET Norway (api.met.no)','hourly':hourly,'daily':daily}
  try:atomic(path,json.dumps(fresh,separators=(',',':')))
  except OSError:pass
  return fresh
 except Exception:
  if cached and fetched and 0<=(now-fetched).total_seconds()<43200:return {**cached,'stale':True}
  return None
SITE_DEFAULTS={
 'site_name':'Harpenden Weather Station','tagline':'Live weather, forecast and camera for Harpenden, Hertfordshire',
 'about':['This is a personal weather station in Harpenden, Hertfordshire, run as a hobby and publishing live conditions around the clock.','The pages show live readings, graphs, a forecast and a camera view of the sky. Readings are measured on site and are for information only; they are not an official forecast or warning.'],
 'station':{'Location':'Harpenden, Hertfordshire, UK','Weather station':'Davis Vantage Pro2','Data logger':'Meteobridge Pro2','Camera':'Raspberry Pi weather camera','Dashboard':'HWS-Webcam-Control'},
 'links':[],
 'news':[],'donate':'','radar_rain':'','radar_satellite':'',
}
def site_content():
 """Static page text, optionally overridden by the JSON file named in DASHBOARD_SITE_CONTENT."""
 out={**SITE_DEFAULTS}
 try:custom=json.loads(Path(os.environ['DASHBOARD_SITE_CONTENT']).read_text(encoding='utf-8'))
 except (KeyError,OSError,ValueError):custom={}
 if isinstance(custom,dict):
  for key in out:
   if key in custom and isinstance(custom[key],type(out[key])):out[key]=custom[key]
 out['latitude']=LATITUDE;out['longitude']=LONGITUDE
 return out

def records_data(daily,now):
 """Weather records for this month, this year and all stored days, from the daily rows."""
 scopes={'month':now.strftime('%Y-%m'),'year':now.strftime('%Y'),'all':''}
 picks=(('hottest_c','temp_max_c',max),('coldest_c','temp_min_c',min),('wettest_mm','rain_mm',max),('gust_mph','wind_gust_mph',max),('pressure_high_hpa','pressure_max_hpa',max),('pressure_low_hpa','pressure_min_hpa',min))
 out={}
 for scope,prefix in scopes.items():
  rows=[r for r in daily if str(r.get('date','')).startswith(prefix)];rec={'days':len(rows),'first':rows[0]['date'] if rows else None}
  for name,key,fn in picks:
   vals=[(r[key],r['date']) for r in rows if num(r.get(key)) is not None]
   if vals:
    best=fn(vals,key=lambda x:x[0]);rec[name]={'value':best[0],'date':best[1]}
  rain=[num(r.get('rain_mm')) for r in rows if num(r.get('rain_mm')) is not None]
  if rain:rec['rain_total_mm']=round(sum(rain),1);rec['rain_days']=sum(v>=0.2 for v in rain)
  out[scope]=rec
 return out
def almanac_data(now,days=14):
 """Sun times, moon and the astronomical dark window (sun below -18 degrees) for the coming days."""
 rows=[]
 for offset in range(days):
  day=(now+timedelta(days=offset)).date();times=sun_times(day)
  noon=datetime(day.year,day.month,day.day,12,tzinfo=timezone.utc);moon=moon_phase(noon)
  start=datetime(day.year,day.month,day.day,12,tzinfo=timezone.utc);dark=[m for m in range(0,1440,10) if solar_elevation(start+timedelta(minutes=m))<-18]
  row={'date':day.isoformat(),'moon':moon['phase'],'moon_illumination':moon['illumination_percent'],
   'dark_start':(start+timedelta(minutes=dark[0])).isoformat() if dark else None,'dark_end':(start+timedelta(minutes=dark[-1]+10)).isoformat() if dark else None}
  if times:row.update({'sunrise':times[0].isoformat(),'sunset':times[1].isoformat(),'day_length_seconds':int((times[1]-times[0]).total_seconds())})
  rows.append(row)
 return rows
REDIRECTS=(('index.php','/indexnew.html'),('about.php','/about.html'),('weather.php','/console.html'),('console.php','/console.html'),('mobile.php','/mobile.html'),('webcam.php','/webcam.html'),('timelapse.php','/webcam.html'),('radar.php','/radar.html'),('satellite.php','/radar.html'),('records.php','/records.html'),('tags.php','/data.html'),('health.php','/health.html'),('donate.php','/about.html'),('history.php','/reports.html'),('today.php','/graphs.html'),('last7days.php','/graphs.html'),('thismonth.php','/reports.html'),('thisyear.php','/reports.html'))
def redirects_htaccess():
 """Apache rules sending the old site's page URLs to the new pages (copied to the web root at cut-over)."""
 head='# Generated by the weather dashboard: copy to the site root (as .htaccess) when the new site replaces the old one.\nRewriteEngine On\n'
 return head+''.join('RewriteRule ^'+old.replace('.','\\.')+'$ '+new.lstrip('/')+' [R=301,L]\n' for old,new in REDIRECTS)
