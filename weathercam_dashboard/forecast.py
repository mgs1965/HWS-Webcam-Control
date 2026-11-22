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
