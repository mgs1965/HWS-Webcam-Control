# Weather-station data, insight and event helpers (included into dashboard.py).
def weather_history():
 p=LD/'weather_station_history.json'
 try:data=json.loads(p.read_text(errors='ignore'))
 except (OSError,ValueError):return None
 return data if isinstance(data,dict) and (data.get('daily') or data.get('year_records')) else None
def weather_series(now,hours=24):
 try:data=json.loads((LD/'weather_station_series.json').read_text(errors='ignore'))
 except (OSError,ValueError):return []
 out=[];cutoff=now-timedelta(hours=hours)
 for r in data.get('samples',[]) if isinstance(data,dict) else []:
  try:t=datetime.fromisoformat(str(r.get('t')))
  except (ValueError,TypeError,AttributeError):continue
  if t.tzinfo is None:t=t.replace(tzinfo=now.tzinfo)
  if cutoff<=t<=now:out.append({'t':t.isoformat(),**{k:num(r.get(k)) for k in ('temperature_c','humidity_percent','pressure_hpa','wind_speed_mph','wind_gust_mph','wind_direction_deg','dew_point_c','rain_today_mm','lightning_strikes_today','lightning_distance','solar_radiation_wm2','uv_index')}})
 return out
def weather_raw():
 try:raw=json.loads((LD/'weather_station_raw.json').read_text(errors='ignore'));labels=json.loads((Path(__file__).resolve().parent/'weather_labels.json').read_text())
 except (OSError,ValueError):return {}
 out={}
 for name,info in (raw.items() if isinstance(raw,dict) else []):
  if not isinstance(info,dict) or not isinstance(info.get('tokens'),list):continue
  names=labels.get(name,{})
  out[name]={'fetched':str(info.get('fetched',''))[:40],'rows':[[i,(names.get(str(i)) or {}).get('l',''),(names.get(str(i)) or {}).get('u',''),str(v)[:24]] for i,v in enumerate(info['tokens'],1)]}
 return out
def solar_check(weather,scene,now):
 w=weather or {};s=scene or {};solar=num(w.get('solar_radiation_wm2'))
 if solar is None:return None
 elev=solar_elevation(now)
 if elev<10:return None
 clear=max(1.0,990*math.sin(math.radians(elev))-30);cloud=max(0.0,min(100.0,(1-solar/clear)*100))
 out={'elevation':round(elev,1),'clear_sky_wm2':round(clear),'solar_cloud_pct':round(cloud)}
 cam=num(s.get('cloud_cover_pct'))
 if cam is not None and not s.get('analysis_paused'):
  out['camera_cloud_pct']=round(cam);diff=cam-cloud
  if diff>=40:out['verdict']='CAMERA_CLOUDIER';out['note']=f'Camera sees {cam:.0f}% cloud but the solar sensor suggests {cloud:.0f}%: check the lens for fog, droplets or dirt.'
  elif diff<=-40:out['verdict']='CAMERA_CLEARER';out['note']=f'Camera sees {cam:.0f}% cloud but the solar sensor suggests {cloud:.0f}%: thin or distant cloud, or the sun is shaded.'
  else:out['verdict']='AGREE';out['note']=f'Camera cloud ({cam:.0f}%) and solar estimate ({cloud:.0f}%) agree.'
 return out
def record_notes(weather,history):
 w=weather or {};r=(history or {}).get('year_records') or {};notes=[]
 for key,field,hi,label in (('temp_max_c','temperature_c',True,'temperature high'),('temp_min_c','temperature_c',False,'temperature low'),('pressure_max_hpa','pressure_hpa',True,'pressure high'),('pressure_min_hpa','pressure_hpa',False,'pressure low')):
  v,rec=num(w.get(field)),num((r.get(key) or {}).get('value'))
  if v is None or rec is None:continue
  if (v>=rec) if hi else (v<=rec):notes.append(f'Year-to-date {label} matched or broken: {v:.1f} (previous record {rec:.1f}).')
 return notes
def frost_notes(weather):
 w=weather or {};t,d=num(w.get('temperature_c')),num(w.get('dew_point_c'))
 if t is None:return []
 if t<=0:return [f'Freezing: air {t:.1f} °C. Ice or frost on the lens or housing is possible.']
 if t<=3 and (d is None or d<=1):return [f'Frost risk: air {t:.1f} °C'+(f', dew point {d:.1f} °C' if d is not None else '')+'.']
 return []
def _hour_block(tokens,start,scale=1.0):
 out=[]
 for i in range(60):
  try:v=float(tokens[start-1+i])*scale
  except (IndexError,ValueError):v=None
  out.append(v if v is not None and math.isfinite(v) else None)
 return out
def _minute_hour():
 try:samples=json.loads((LD/'weather_station_minute.json').read_text(errors='ignore')).get('samples')
 except (OSError,ValueError,AttributeError):return {}
 pts=[]
 for x in samples if isinstance(samples,list) else []:
  try:pts.append((datetime.fromisoformat(str(x.get('t'))),x))
  except (ValueError,TypeError,AttributeError):pass
 if len(pts)<5:return {}
 end=pts[-1][0];out={'fetched':end.isoformat(),'source':'local'}
 for name,key,scale in (('wind_mph','wind_speed_mph',1),('gust_mph','wind_gust_mph',1),('direction_deg','wind_direction_deg',1),('temperature_c','temperature_c',1),('humidity_percent','humidity_percent',1),('pressure_hpa','pressure_hpa',1),('solar_wm2','solar_radiation_wm2',1)):
  col=[None]*60
  for t,x in pts:
   age=(end-t).total_seconds()/60
   if age>59.5:continue
   i=59-int(round(age));v=num(x.get(key))
   if v is not None and 0<=i<60:col[i]=v
  out[name]=col
 return out
def weather_hour():
 try:raw=json.loads((LD/'weather_station_raw.json').read_text(errors='ignore'))
 except (OSError,ValueError):return _minute_hour()
 info=raw.get('clientrawhour') if isinstance(raw,dict) else None;tokens=info.get('tokens') if isinstance(info,dict) else None
 if not isinstance(tokens,list) or len(tokens)<480:return _minute_hour()
 local=_minute_hour()
 try:
  if local and (datetime.fromisoformat(local['fetched'])-datetime.fromisoformat(str(info.get('fetched','')))).total_seconds()>900:return local
 except (ValueError,TypeError):pass
 return {'fetched':str(info.get('fetched',''))[:40],'wind_mph':_hour_block(tokens,1,1.15078),'gust_mph':_hour_block(tokens,61,1.15078),'direction_deg':_hour_block(tokens,121),'temperature_c':_hour_block(tokens,181),'humidity_percent':_hour_block(tokens,241),'pressure_hpa':_hour_block(tokens,301),'solar_wm2':_hour_block(tokens,421)}
def wind_rose(series,hour):
 pts=[(num(p.get('wind_direction_deg')),num(p.get('wind_speed_mph')) or 0) for p in series]
 source='24 h'
 if sum(1 for d,_ in pts if d is not None)<6 and hour:
  pts=list(zip(hour.get('direction_deg',[]),[v or 0 for v in hour.get('wind_mph',[])]));source='last hour'
 bins=[0.0]*16;n=0
 for d,sp in pts:
  if d is None or not 0<=d<=360:continue
  bins[int(((d%360)+11.25)//22.5)%16]+=1;n+=1
 if n<6:return {}
 return {'source':source,'samples':n,'percent':[round(100*b/n,1) for b in bins]}
def weather_summary(series):
 if not series:return {}
 def col(k):return [v for v in (num(p.get(k)) for p in series) if v is not None]
 out={'samples':len(series),'from':series[0]['t'],'to':series[-1]['t']}
 for key,field,fn in (('temp_min_c','temperature_c',min),('temp_max_c','temperature_c',max),('humidity_max','humidity_percent',max),('gust_max_mph','wind_gust_mph',max),('solar_max_wm2','solar_radiation_wm2',max),('uv_max','uv_index',max),('rain_today_mm','rain_today_mm',max),('lightning_today','lightning_strikes_today',max),('pressure_min_hpa','pressure_hpa',min),('pressure_max_hpa','pressure_hpa',max)):
  v=col(field)
  if v:out[key]=round(fn(v),1)
 return out
def weather_events(series):
 events=[];last_light=None;fog_on=False
 for p in series:
  t=dt(p.get('t'))
  if not t:continue
  l=num(p.get('lightning_strikes_today'))
  if l is not None and last_light is not None and l>last_light:
   d=num(p.get('lightning_distance'));events.append({'time':p['t'],'severity':'WARNING','message':f'Lightning: {l-last_light:.0f} new strike(s)'+(f', last strike distance {d:g}' if d is not None else '')})
  if l is not None:last_light=l
  tt,dp,h=num(p.get('temperature_c')),num(p.get('dew_point_c')),num(p.get('humidity_percent'))
  fog=tt is not None and dp is not None and h is not None and h>=95 and tt-dp<=1
  if fog and not fog_on:events.append({'time':p['t'],'severity':'WARNING','message':f'Fog conditions: humidity {h:.0f}%, air within {tt-dp:.1f} °C of dew point'})
  fog_on=fog
 return events[-20:]
def scene_history(now,hours=24,limit=144):
 out=[]
 cutoff=now-timedelta(hours=hours)
 for day in sorted({cutoff.date(),now.date()}):
  p=LD/'scene'/f'scene_{day:%Y%m%d}.jsonl'
  try:lines=p.read_text(errors='ignore').splitlines()
  except OSError:continue
  for line in lines:
   try:r=json.loads(line);t=datetime.fromisoformat(str(r.get('timestamp')))
   except (ValueError,TypeError):continue
   if t.tzinfo is None:t=t.replace(tzinfo=now.tzinfo)
   if t<cutoff or t>now:continue
   out.append({'t':t.isoformat(),**{k:num(r.get(k)) for k in ('cloud_cover_pct','sky_clarity_pct','fog_index','droplet_score','temperature_c','humidity_percent','solar_radiation_wm2','uv_index')}})
 if len(out)>limit:out=[out[round(i*(len(out)-1)/(limit-1))] for i in range(limit)]
 return out
def weather_insight(weather,scene):
 w=weather or {};reasons=[]
 t,h,d=num(w.get('temperature_c')),num(w.get('humidity_percent')),num(w.get('dew_point_c'))
 risk=(scene or {}).get('fog_risk')
 if risk in ('HIGH','MODERATE') and h is not None:
  detail=f'humidity {h:.0f}%'
  if t is not None and d is not None:detail+=f', air {t:.1f} °C within {t-d:.1f} °C of the dew point'
  reasons.append(f'Fog risk {risk.lower()}: {detail}.')
 tc=num(w.get('temp_change_1h_c'))
 if tc is not None and tc<=-3:reasons.append(f'Temperature fell {abs(tc):.1f} °C in the last hour.')
 g=num(w.get('wind_gust_max_1h_mph'))
 if g is not None and g>=25:reasons.append(f'Gusts up to {g:.0f} mph in the last hour (possible camera shake).')
 gt=num(w.get('wind_gust_max_today_mph'))
 if gt is not None and gt>=25 and (g is None or gt>g):reasons.append(f'Gusts up to {gt:.0f} mph today.')
 ls,lt=num(w.get('lightning_strikes_last_min')),num(w.get('lightning_strikes_today'))
 if ls is not None and ls>0:reasons.append(f'Lightning detected: {ls:.0f} strike(s) in the last minute.')
 elif lt is not None and lt>0:reasons.append(f'Lightning detected today: {lt:.0f} strike(s) since noon.')
 r=num(w.get('rain_rate_mm_h'))
 if r is not None and r>0:reasons.append(f'Rain reported ({r:.1f} mm/h); droplets on the lens are likely.')
 return reasons
COMPARE_FIELDS=(('temperature_c','Temperature','°C',0.5),('humidity_percent','Humidity','%',3),('pressure_hpa','Pressure','hPa',1.5),('wind_speed_mph','Wind speed','mph',2),('wind_gust_mph','Wind gust','mph',3),('wind_direction_deg','Wind direction','°',20),('dew_point_c','Dew point','°C',0.7),('rain_rate_mm_h','Rain rate','mm/h',0.5),('rain_today_mm','Rain today','mm',0.3),('uv_index','UV index','',0.3),('solar_radiation_wm2','Solar','W/m²',30),('wind_gust_max_today_mph','Max gust today','mph',3),('lightning_strikes_today','Lightning today','',0))
def weather_compare():
 try:d=json.loads((LD/'weather_station_compare.json').read_text(errors='ignore'))
 except (OSError,ValueError):return {}
 if not isinstance(d,dict) or not isinstance(d.get('clientraw'),dict) or not isinstance(d.get('meteobridge'),dict):return {}
 rows=[]
 for key,label,unit,tol in COMPARE_FIELDS:
  a=num(d['clientraw'].get(key));b=num(d['meteobridge'].get(key))
  if a is None and b is None:continue
  diff=None if a is None or b is None else round(b-a,2)
  if key=='wind_direction_deg' and diff is not None:diff=round((diff+180)%360-180,2)
  rows.append({'label':label,'unit':unit,'clientraw':a,'meteobridge':b,'diff':diff,'status':'missing' if diff is None else ('differs' if abs(diff)>tol else 'match')})
 return {'updated':str(d.get('updated',''))[:40],'rows':rows}
