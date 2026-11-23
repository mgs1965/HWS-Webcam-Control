# Predictive analytics, event detection, daily summaries and long-term statistics (included into dashboard.py).
QUALITY_BANDS=((75,'GOOD'),(60,'FAIR'),(40,'WARNING'))
SCENE_FIELDS=('cloud_cover_pct','sky_clarity_pct','fog_index','visibility','droplet_score','lens_condition','focus','alerts','fog_risk','mode','temperature_c','humidity_percent','pressure_hpa','wind_speed_mph','rain_rate_mm_h','rain_today_mm','dew_point_c','solar_radiation_wm2','wind_direction_deg','wind_gust_mph','ground_temperature_c','soil_wetness_cbar','soil_temperature_c','greenhouse_temperature_c','cpu_load_percent','bridge_uptime_hours','storage_usage_percent','ram_usage_percent','power_consumption_w','process_count','bridge_data_age_s','voltage_v','current_a','signal_min','signal_max')
FOG_WARNING_INDEX=35.0
DAILY_STATS_DAYS=1200
def quality_label(value):
 if value is None:return None
 for floor,label in QUALITY_BANDS:
  if value>=floor:return label
 return 'CRITICAL'
def _median(values):
 values=sorted(values)
 if not values:return None
 mid=len(values)//2
 return values[mid] if len(values)%2 else (values[mid-1]+values[mid])/2
def _mean(values):
 return sum(values)/len(values) if values else None
def _pearson(xs,ys):
 n=len(xs)
 if n<3:return None
 mx,my=sum(xs)/n,sum(ys)/n
 sx=math.sqrt(sum((x-mx)**2 for x in xs));sy=math.sqrt(sum((y-my)**2 for y in ys))
 if sx==0 or sy==0:return None
 return sum((x-mx)*(y-my) for x,y in zip(xs,ys))/(sx*sy)
def _fit(points):
 """Least-squares slope and r-squared for [(x,y)]."""
 n=len(points)
 if n<3:return None,None
 mx=sum(p[0] for p in points)/n;my=sum(p[1] for p in points)/n
 sxx=sum((p[0]-mx)**2 for p in points)
 if sxx==0:return None,None
 sxy=sum((p[0]-mx)*(p[1]-my) for p in points);slope=sxy/sxx
 r=_pearson([p[0] for p in points],[p[1] for p in points])
 return slope,(r*r if r is not None else 0.0)
def scene_records(now,days=30):
 """Scene-analysis history (sampled about once a minute) for the last `days` days, oldest first."""
 cutoff=now-timedelta(days=days);out=[]
 try:files=sorted((LD/'scene').glob('scene_*.jsonl'))[-(days+2):]
 except OSError:return out
 for path in files:
  try:lines=path.read_text(errors='ignore').splitlines()
  except OSError:continue
  for line in lines:
   try:r=json.loads(line);t=datetime.fromisoformat(str(r.get('timestamp')))
   except (ValueError,TypeError):continue
   if not isinstance(r,dict):continue
   if t.tzinfo is None:t=t.replace(tzinfo=now.tzinfo)
   t=t.astimezone(timezone.utc)
   if t<cutoff or t>now:continue
   rec={'t':t};alerts=r.get('alerts')
   for key in SCENE_FIELDS:
    value=weather_sample_value(r,key)
    rec[key]=value if key in ('visibility','lens_condition','focus','fog_risk','mode') else (list(alerts) if key=='alerts' and isinstance(alerts,(list,tuple)) else ([] if key=='alerts' else num(value)))
   out.append(rec)
 return sorted(out,key=lambda r:r['t'])
def _telemetry_points(tele,field):
 return [(r['_ts'],v) for r in tele for v in [num(r.get(field))] if r.get('_ts') and v is not None]
def _nearest(rows,stamp,limit=300):
 """Row whose '_ts' is closest to `stamp` within `limit` seconds (rows sorted by '_ts')."""
 lo,hi=0,len(rows)
 while lo<hi:
  mid=(lo+hi)//2
  if rows[mid]['_ts']<stamp:lo=mid+1
  else:hi=mid
 best=None
 for i in (lo-1,lo):
  if 0<=i<len(rows):
   gap=abs((rows[i]['_ts']-stamp).total_seconds())
   if gap<=limit and (best is None or gap<best[0]):best=(gap,rows[i])
 return best[1] if best else None
def _strength(r):
 a=abs(r)
 return 'no clear relationship' if a<0.2 else 'weak' if a<0.4 else 'moderate' if a<0.6 else 'strong'
def correlations(scene,tele,now,days=7,minimum=30):
 """Pearson correlations between camera quality measures and the weather at the same time."""
 cut=now-timedelta(days=days);scene=[r for r in scene if r['t']>=cut]
 tele=sorted([r for r in tele if r.get('_ts') and r['_ts']>=cut],key=lambda r:r['_ts'])
 def direct(xk,yk,fn=None):
  pairs=[]
  for r in scene:
   x=r.get(xk);y=r.get(yk)
   if x is None or y is None:continue
   pairs.append((x,fn(y) if fn else y))
  return pairs
 def joined(xk,field,mode=None,sun_min=None):
  pairs=[]
  for r in scene:
   x=r.get(xk)
   if x is None or (mode and r.get('mode')!=mode):continue
   if sun_min is not None and solar_elevation(r['t'])<sun_min:continue
   t=_nearest(tele,r['t']);y=num(t.get(field)) if t else None
   if y is not None:pairs.append((x,y))
  return pairs
 specs=(
  ('Visibility vs humidity','Humidity','Visibility index',direct('humidity_percent','fog_index',lambda v:100-v),'visibility falls as humidity rises','visibility improves as humidity rises'),
  ('Fog vs temperature','Temperature','Fog score',direct('temperature_c','fog_index'),'fog scores rise as the air warms','fog scores rise as the air cools'),
  ('Sharpness vs wind','Wind speed','Sharpness',joined('wind_speed_mph','sharpness_score','DAY'),'sharpness improves as the wind rises','sharpness falls as the wind rises'),
  ('Cloud cover vs brightness','Cloud cover','Brightness',joined('cloud_cover_pct','brightness_raw','DAY',15),'the image gets brighter as cloud increases','the image gets darker as cloud increases'),
 )
 out=[]
 for name,xl,yl,pairs,positive,negative in specs:
  item={'pair':name,'x':xl,'y':yl,'n':len(pairs),'r':None}
  r=_pearson([p[0] for p in pairs],[p[1] for p in pairs]) if len(pairs)>=minimum else None
  if r is None:item['text']=f'Not enough data yet ({len(pairs)} of {minimum} samples).'
  else:
   item['r']=round(r,2);strength=_strength(r)
   item['text']='No clear relationship' if strength=='no clear relationship' else f'{strength.capitalize()}: {positive if r>0 else negative}'
   item['text']+=f' (r {r:+.2f}, {len(pairs)} samples).'
  out.append(item)
 return {'window_days':days,'items':out}
def quality_explanation(scene,tele,now,hours=24):
 """Find the worst half-hour of image quality in the window and list the likely causes."""
 cut=now-timedelta(hours=hours);buckets={}
 for t,v in _telemetry_points(tele,'image_quality_score'):
  if t>=cut:buckets.setdefault(int(t.timestamp()//1800),[]).append(v)
 buckets={k:v for k,v in buckets.items() if len(v)>=3}
 if not buckets:return {'status':'NO DATA','text':'No image-quality scores in the last 24 hours.'}
 key=min(buckets,key=lambda k:_mean(buckets[k]));score=_mean(buckets[key]);start=datetime.fromtimestamp(key*1800,timezone.utc)
 out={'status':'GOOD','when':start.isoformat(),'quality':round(score,1),'label':quality_label(score),'factors':[]}
 if score>=60:
  out['text']=f'Image quality stayed good: the lowest half-hour averaged {score:.0f} ({quality_label(score)}).';return out
 out['status']='POOR'
 near=[r for r in scene if abs((r['t']-start).total_seconds())<=1800+900]
 before=[r for r in scene if start-timedelta(hours=3)<=r['t']<=start and r.get('temperature_c') is not None]
 def avg(k):return _mean([r[k] for r in near if r.get(k) is not None])
 factors=out['factors'];hum=avg('humidity_percent');fog=avg('fog_index');wind=avg('wind_speed_mph');rain=avg('rain_rate_mm_h')
 if hum is not None and hum>=90:factors.append(f'{hum:.0f}% humidity')
 if len(before)>=2:
  drop=before[0]['temperature_c']-before[-1]['temperature_c']
  if drop>=3:factors.append(f'{drop:.0f} °C temperature drop')
 if (fog is not None and fog>=FOG_WARNING_INDEX) or any('FOG' in (r.get('alerts') or []) for r in near):factors.append('fog detected'+(f' (index {fog:.0f})' if fog is not None else ''))
 if any('LENS_DROPLETS' in (r.get('alerts') or []) for r in near) or (rain is not None and rain>0):factors.append('rain or droplets on the lens')
 if wind is not None and wind>=20:factors.append(f'{wind:.0f} mph wind (camera shake)')
 if any('FOCUS_DRIFT' in (r.get('alerts') or []) for r in near):factors.append('focus drift')
 night=[r for r in near if r.get('mode')=='NIGHT']
 if night and not factors:factors.append('night-time long exposure (expected, not a fault)')
 when=start.strftime('%H:%M')
 out['text']=f'Image quality was lowest around {when} UTC (score {score:.0f}, {quality_label(score)})'+(' due to: '+', '.join(factors)+'.' if factors else ': no weather cause found, so check the lens and focus.')
 return out
def lens_maintenance(scene,tele,now,days=30,min_days=7):
 """Daytime lens-quality trend over weeks; a large day-on-day improvement is treated as a cleaning."""
 cut=now-timedelta(days=days);sharp={};qual={};drops={}
 for r in tele:
  t=r.get('_ts')
  if not t or t<cut or str(r.get('camera_mode')).upper()!='DAY':continue
  day=t.date().isoformat();s=num(r.get('sharpness_score'));q=num(r.get('image_quality_score'))
  if s is not None:sharp.setdefault(day,[]).append(s)
  if q is not None:qual.setdefault(day,[]).append(q)
 for r in scene:
  if r['t']<cut or r.get('mode')!='DAY' or r.get('droplet_score') is None:continue
  if (r.get('fog_index') or 0)>=FOG_WARNING_INDEX or (r.get('rain_rate_mm_h') or 0)>0:continue
  drops.setdefault(r['t'].date().isoformat(),[]).append(r['droplet_score'])
 valid=sorted(day for day in set(sharp)|set(qual) if len(qual.get(day,[]))>=20 or len(sharp.get(day,[]))>=20)
 if len(valid)<min_days:return {'status':'LEARNING','days':len(valid),'text':f'Collecting daytime data: {len(valid)} of {min_days} days.'}
 daily={d:{'sharp':_median(sharp.get(d,[])),'qual':_median(qual.get(d,[])),'drop':_median(drops.get(d,[]))} for d in valid}
 note=None;primary='qual' if all(daily[d]['qual'] is not None for d in valid) else 'sharp'
 for i in range(1,len(valid)):
  a,b=daily[valid[i-1]][primary],daily[valid[i]][primary]
  if a and b and b/a>=1.15 and i<len(valid)-1:cut_index=i;note=f'Looks cleaned around {valid[i]}; trend restarted from that day.'
 start=0
 if note:start=cut_index
 window=valid[start:]
 if len(window)<min_days and note:
  return {'status':'OK','recommendation':'No cleaning needed','confidence':70,'days':len(window),'days_worsening':0,'metrics':[],'text':'Lens looks recently cleaned. '+f'Trend needs {min_days} days after cleaning ({len(window)} so far).'}
 base=datetime.fromisoformat(window[0]).date();metrics=[];flagged=[]
 for label,key,unit,bad_sign,threshold in (('Sharpness','sharp','%',-1,10.0),('Image quality','qual',' pts',-1,8.0),('Droplet score','drop',' pts',1,8.0)):
  pts=[((datetime.fromisoformat(d).date()-base).days,daily[d][key]) for d in window if daily[d][key] is not None]
  if len(pts)<min_days:continue
  slope,r2=_fit(pts)
  if slope is None:continue
  change=slope*(pts[-1][0]-pts[0][0]);mean=_mean([p[1] for p in pts])
  value=change/mean*100 if key=='sharp' and mean else change
  bad=value*bad_sign>=threshold and r2>=0.3
  metrics.append({'name':label,'change':round(value,1),'unit':unit,'r2':round(r2,2),'worsening':bad})
  if bad:flagged.append(r2)
 worst_days=0
 series=[daily[d][primary] for d in window if daily[d][primary] is not None]
 if len(series)>=3:
  smooth=[_mean(series[max(0,i-2):i+1]) for i in range(len(series))];peak=max(range(len(smooth)),key=lambda i:smooth[i]);worst_days=len(series)-1-peak if flagged else 0
 confidence=round(min(95,(_mean(flagged)*100 if flagged else 60)*min(1.0,len(window)/14))) if metrics else 0
 if len(flagged)>=2:rec='Lens cleaning recommended'
 elif flagged:rec='Watch the lens: one measure is trending worse'
 else:rec='No cleaning needed'
 text=rec+(f'. Confidence {confidence}%, trend worsening for {worst_days} days.' if flagged else f'. No worsening trend over {len(window)} days.')
 if note:text+=' '+note
 return {'status':'CLEAN' if len(flagged)>=2 else 'WATCH' if flagged else 'OK','recommendation':rec,'confidence':confidence,'days':len(window),'days_worsening':worst_days,'metrics':metrics,'text':text}
def quality_forecast(tele,now,history_days=14):
 """Expected image quality an hour ahead and after sunset, from today's trend and the same time on previous days."""
 pts=sorted(_telemetry_points(tele,'image_quality_score'),key=lambda p:p[0])
 recent=[v for t,v in pts if t>=now-timedelta(minutes=30)]
 if len(recent)<3:
  recent=[v for t,v in pts if t>=now-timedelta(minutes=90)]
 if len(recent)<3:return None
 current=_mean(recent);trend_pts=[((t-now).total_seconds()/3600,v) for t,v in pts if t>=now-timedelta(minutes=90)]
 slope,_=_fit(trend_pts) if len(trend_pts)>=10 else (None,None)
 slope=max(-15.0,min(15.0,slope)) if slope is not None else 0.0
 def history(at):
  vals=[]
  for back in range(1,history_days+1):
   centre=at(back)
   if centre is None:continue
   day=[v for t,v in pts if abs((t-centre).total_seconds())<=1200]
   if len(day)>=3:vals.append(_mean(day))
  return vals
 def predict(at,hours_ahead):
  vals=history(at);hist=_mean(vals)
  if hist is None:return {'score':round(max(0,min(100,current+slope*hours_ahead)),1),'confidence':35,'days':0}
  std=math.sqrt(sum((v-hist)**2 for v in vals)/len(vals))
  score=0.4*current+0.6*hist+0.25*slope*hours_ahead
  confidence=max(30,min(95,round(95-1.2*std-max(0,7-len(vals))*5)))
  return {'score':round(max(0,min(100,score)),1),'confidence':confidence,'days':len(vals)}
 target=now+timedelta(hours=1);nxt=predict(lambda back:target-timedelta(days=back),1);nxt['label']=quality_label(nxt['score']);nxt['time']=target.isoformat()
 out={'current':{'score':round(current,1),'label':quality_label(current)},'next_hour':nxt,'trend':'DEGRADING' if slope<=-3 else 'IMPROVING' if slope>=3 else 'STABLE','trend_per_hour':round(slope,1)}
 sunset=None
 for offset in (0,1):
  times=sun_times((now+timedelta(days=offset)).date())
  if times and times[1]+timedelta(minutes=30)>now:sunset=times[1]+timedelta(minutes=30);break
 if sunset:
  def at_sunset(back):
   times=sun_times((sunset-timedelta(days=back)).date())
   return times[1]+timedelta(minutes=30) if times else None
  after=predict(at_sunset,max(0,(sunset-now).total_seconds()/3600));after['label']=quality_label(after['score']);after['time']=sunset.isoformat();out['after_sunset']=after
 text=f"Current quality: {out['current']['label']} ({current:.0f}). Expected next hour: {nxt['label']} ({nxt['score']:.0f}, confidence {nxt['confidence']}%)."
 if 'after_sunset' in out:text+=f" Expected after sunset: {out['after_sunset']['label']} (confidence {out['after_sunset']['confidence']}%)."
 out['text']=text
 return out
def smart_events(scene,series,now):
 """Rapid fog formation, sunset cloud break, heavy rain onset, possible snow and sudden visibility collapse."""
 events=[];last={}
 def emit(kind,stamp,message,cooldown):
  if kind in last and (stamp-last[kind]).total_seconds()<cooldown*60:return
  last[kind]=stamp;events.append({'time':stamp.isoformat(),'severity':'WARNING','message':f'{kind}: {message}'})
 recent=[];rain_on=False
 for r in scene:
  t=r['t'];recent.append(r)
  while recent and (t-recent[0]['t']).total_seconds()>3600:recent.pop(0)
  fog=r.get('fog_index')
  if fog is not None and fog>=FOG_WARNING_INDEX:
   prior=[(x['t'],x['fog_index']) for x in recent if x.get('fog_index') is not None]
   low=min(prior,key=lambda p:p[1]) if prior else None
   if low:
    quick=[p for p in prior if (t-p[0]).total_seconds()<=900]
    quick_low=min(quick,key=lambda p:p[1]) if quick else None
    if quick_low and fog-quick_low[1]>=40:emit('Sudden visibility collapse',t,f'fog index {quick_low[1]:.0f} to {fog:.0f} in {(t-quick_low[0]).total_seconds()/60:.0f} min',90)
    elif fog-low[1]>=25:emit('Rapid fog formation',t,f'fog index {low[1]:.0f} to {fog:.0f} in {(t-low[0]).total_seconds()/60:.0f} min',90)
  cloud=r.get('cloud_cover_pct')
  if cloud is not None and cloud<=40:
   elev=solar_elevation(t)
   if -1<=elev<=12 and solar_elevation(t+timedelta(minutes=10))<elev:
    clouds=[(x['t'],x['cloud_cover_pct']) for x in recent if x.get('cloud_cover_pct') is not None and (t-x['t']).total_seconds()<=2700]
    peak=max(clouds,key=lambda p:p[1]) if clouds else None
    if peak and peak[1]>=70 and peak[1]-cloud>=30:emit('Sunset cloud break',t,f'cloud cover fell from {peak[1]:.0f}% to {cloud:.0f}% in {(t-peak[0]).total_seconds()/60:.0f} min',120)
  rate=r.get('rain_rate_mm_h')
  if rate is not None:
   if rate>=4 and not rain_on:emit('Heavy rain onset',t,f'rain rate {rate:.1f} mm/h',60)
   rain_on=rate>=1 if rate>=1 or rain_on is False else (rate>=1)
  temp=r.get('temperature_c')
  if temp is not None and temp<=1.5 and ((rate or 0)>0 or 'LENS_DROPLETS' in (r.get('alerts') or [])) and (r.get('dew_point_c') is None or r['dew_point_c']<=0.5):
   emit('Snow detected',t,f'precipitation at {temp:.1f} °C (possible snow or sleet)',180)
 previous=None;heavy=False
 for point in series or []:
  stamp=dt(point.get('t'));rain=num(point.get('rain_today_mm'))
  if not stamp or rain is None:continue
  if previous and 0<(stamp-previous[0]).total_seconds()<=900 and rain>=previous[1]:
   hours=(stamp-previous[0]).total_seconds()/3600;rate=(rain-previous[1])/hours
   if rate>=4 and not heavy:emit('Heavy rain onset',stamp,f'about {rate:.1f} mm/h (station rain total)',60)
   heavy=rate>=1
   temp=num(point.get('temperature_c'))
   if temp is not None and temp<=1.5 and rain>previous[1]:emit('Snow detected',stamp,f'precipitation at {temp:.1f} °C (possible snow or sleet)',180)
  previous=(stamp,rain)
 return sorted(events,key=lambda e:e['time'])[-40:]
def _health_word(overall,completeness):
 overall=str(overall or '').upper()
 if overall in ('CRITICAL','FAILED','UNHEALTHY'):return 'Poor'
 if completeness is not None and completeness<90:return 'Poor'
 if overall in ('WARNING','DEGRADED') or (completeness is not None and completeness<98):return 'Fair'
 if overall in ('HEALTHY','OK','GOOD','EXCELLENT') and (completeness is None or completeness>=99.5):return 'Excellent'
 return 'Good' if overall else 'Unknown'
def daily_summary(day,tele,scene,reports,incident_rows,partial=False):
 """Plain-language summary of one day from data the dashboard already holds."""
 iso=day.isoformat()
 rows=[r for r in tele if r.get('_ts') and r['_ts'].date()==day]
 recs=[r for r in scene if r['t'].date()==day]
 report=next((r for r in reports if str(r.get('date'))[:10]==iso),None)
 if not rows and not recs and not report:return None
 lines=[];completeness=num(report.get('capture_completeness_percent')) if report else None
 health=_health_word(report.get('overall') if report else None,completeness) if report else 'Unknown'
 lines.append(('System health',health))
 if report and num(report.get('captures')) is not None:
  expected=num(report.get('captures_expected'))
  lines.append(('Captures',f"{num(report.get('captures')):.0f}"+(f'/{expected:.0f}' if expected else '')))
 modes=[];changes=[]
 for r in sorted(rows,key=lambda r:r['_ts']):
  mode=str(r.get('camera_mode') or '').upper()
  if mode and (not modes or modes[-1]!=mode):
   modes.append(mode)
 if len(modes)>1:lines.append(('Mode transitions',f"{len(modes)-1} ({' > '.join(modes)})"))
 ftp=[i for i in incident_rows if str(i.get('timestamp',''))[:10]==iso and 'FTP' in str(i.get('event_type') or i.get('message') or '').upper()]
 lines.append(('FTP incidents',f'{len(ftp)}' if ftp else 'None'))
 scores=[v for _,v in _telemetry_points(rows,'image_quality_score')]
 if scores:lines.append(('Average quality',f'{_mean(scores):.1f} (range {min(scores):.0f}-{max(scores):.0f}, {quality_label(_mean(scores))})'))
 clouds=[(r['cloud_cover_pct'],r['t']) for r in recs if r.get('cloud_cover_pct') is not None]
 if clouds:
  top=max(clouds,key=lambda c:c[0]);lines.append(('Highest cloud cover',f"{top[0]:.0f}% at {top[1]:%H:%M} UTC"))
 fogs=[r['fog_index'] for r in recs if r.get('fog_index') is not None]
 if fogs and max(fogs)>=FOG_WARNING_INDEX:lines.append(('Fog',f'peak fog index {max(fogs):.0f}'))
 lens=[r['lens_condition'] for r in recs if r.get('lens_condition') not in (None,'N/A','')]
 if lens:
  bad=sum(1 for x in lens if x!='CLEAR');lines.append(('Lens condition','Clear' if bad==0 else f'{str(max(set(lens),key=lens.count)).title()} ({100*bad/len(lens):.0f}% of daytime samples)'))
 temps=[r['temperature_c'] for r in recs if r.get('temperature_c') is not None]
 if temps:lines.append(('Temperature',f'{min(temps):.1f} to {max(temps):.1f} °C'))
 rain=[r['rain_rate_mm_h'] for r in recs if r.get('rain_rate_mm_h') is not None]
 if rain and max(rain)>0:lines.append(('Peak rain rate',f'{max(rain):.1f} mm/h'))
 alerts={}
 for r in recs:
  for a in r.get('alerts') or []:alerts[a]=alerts.get(a,0)+1
 if alerts:lines.append(('Scene alerts',', '.join(f'{k} ({v})' for k,v in sorted(alerts.items()))))
 title=f"{day.strftime('%d %b %Y')} summary"+(' (so far)' if partial else '')
 return {'date':iso,'title':title,'health':health,'partial':partial,'lines':[{'label':a,'value':b} for a,b in lines],'text':title+'\n'+'\n'.join(f'{a}: {b}' for a,b in lines)}
def daily_summaries(tele,scene,reports,incident_rows,now,days=7):
 out=[]
 for back in range(0,days):
  day=(now-timedelta(days=back)).date();item=daily_summary(day,tele,scene,reports,incident_rows,partial=back==0)
  if item:out.append(item)
 return out
def _day_stats(day,tele,scene,report):
 rows=[r for r in tele if r.get('_ts') and r['_ts'].date()==day];recs=[r for r in scene if r['t'].date()==day]
 q=[v for _,v in _telemetry_points(rows,'image_quality_score')];out={}
 if q:out['quality_avg']=round(_mean(q),2);out['quality_n']=len(q)
 for key,field,fn in (('fog_avg','fog_index',_mean),('fog_max','fog_index',max),('cloud_avg','cloud_cover_pct',_mean),('clarity_avg','sky_clarity_pct',_mean),('temp_min_c','temperature_c',min),('temp_max_c','temperature_c',max),('rain_max_mm_h','rain_rate_mm_h',max),('rain_mm','rain_today_mm',max),('humidity_avg','humidity_percent',_mean)):
  v=[r[field] for r in recs if r.get(field) is not None]
  if v:out[key]=round(fn(v),2)
 if recs:out['scene_n']=len(recs)
 if report:
  for key,field in (('captures','captures'),('completeness','capture_completeness_percent')):
   v=num(report.get(field))
   if v is not None:out[key]=v
 return out
def update_daily_stats(path,tele,scene,reports,now):
 """Keep one small record per completed day so monthly and yearly reports can outlive the 30-day raw data."""
 try:store=json.loads(path.read_text())
 except (OSError,ValueError):store={}
 days=store.get('days') if isinstance(store,dict) and isinstance(store.get('days'),dict) else {}
 by_date={str(r.get('date'))[:10]:r for r in reports}
 for back in range(1,32):
  day=(now-timedelta(days=back)).date();new=_day_stats(day,tele,scene,by_date.get(day.isoformat()))
  if not new:continue
  old=days.get(day.isoformat()) or {}
  if (new.get('quality_n',0)+new.get('scene_n',0))>=(old.get('quality_n',0)+old.get('scene_n',0)):days[day.isoformat()]={**old,**new}
 days={d:days[d] for d in sorted(days)[-DAILY_STATS_DAYS:]}
 try:atomic(path,json.dumps({'days':days},separators=(',',':')))
 except OSError:pass
 return days
def _composite(stats):
 parts=[stats.get('quality_avg'),stats.get('clarity_avg') if stats.get('clarity_avg') is not None else (100-stats['cloud_avg'] if stats.get('cloud_avg') is not None else None),stats.get('completeness')]
 parts=[p for p in parts if p is not None]
 return _mean(parts)
def _extremes(items):
 out={}
 def pick(name,key,fn,value=lambda s:s):
  cands=[(value(s),d) for d,s in items if key(s) is not None]
  cands=[(key(s),d,s) for d,s in items if key(s) is not None]
  if cands:
   best=fn(cands,key=lambda c:c[0]);out[name]={'date':best[1],'value':round(best[0],1)}
 pick('best_day',_composite,max);pick('worst_day',_composite,min)
 pick('foggiest_day',lambda s:s.get('fog_avg'),max);pick('clearest_day',lambda s:s.get('clarity_avg') if s.get('clarity_avg') is not None else (100-s['cloud_avg'] if s.get('cloud_avg') is not None else None),max)
 pick('highest_quality_day',lambda s:s.get('quality_avg'),max);pick('most_reliable_day',lambda s:s.get('completeness'),max)
 return out
def long_term_report(days):
 """Monthly (and, once enough days exist, year-to-date) best/worst-day statistics from the stored daily records."""
 months={}
 for day,stats in days.items():months.setdefault(day[:7],[]).append((day,stats))
 report=[]
 for month in sorted(months,reverse=True)[:12]:
  items=months[month];entry={'month':month,'days':len(items)}
  entry.update(_extremes(items))
  q=[s['quality_avg'] for _,s in items if s.get('quality_avg') is not None]
  if q:entry['average_quality']=round(_mean(q),1)
  entry['foggy_days']=sum(1 for _,s in items if (s.get('fog_max') or 0)>=FOG_WARNING_INDEX)
  entry['rainy_days']=sum(1 for _,s in items if (s.get('rain_max_mm_h') or 0)>0)
  report.append(entry)
 year=None
 if len(days)>=60:
  latest=max(days)[:4];items=[(d,s) for d,s in days.items() if d.startswith(latest)]
  year={'year':latest,'days':len(items)};year.update(_extremes(items))
  temps=[(s['temp_max_c'],d) for d,s in items if s.get('temp_max_c') is not None];colds=[(s['temp_min_c'],d) for d,s in items if s.get('temp_min_c') is not None]
  if temps:year['warmest_day']={'date':max(temps)[1],'value':round(max(temps)[0],1)}
  if colds:year['coldest_day']={'date':min(colds)[1],'value':round(min(colds)[0],1)}
  year['foggy_days']=sum(1 for _,s in items if (s.get('fog_max') or 0)>=FOG_WARNING_INDEX)
  year['rainy_days']=sum(1 for _,s in items if (s.get('rain_max_mm_h') or 0)>0)
 return {'days_tracked':len(days),'first_day':min(days) if days else None,'months':report,'year':year}
GRAPH_FIELDS=(('temperature_c','mean'),('dew_point_c','mean'),('humidity_percent','mean'),('pressure_hpa','mean'),('wind_speed_mph','mean'),('wind_gust_mph','max'),('rain_rate_mm_h','max'),('rain_today_mm','last'),('solar_radiation_wm2','mean'),('ground_temperature_c','mean'),('soil_wetness_cbar','mean'),('soil_temperature_c','mean'),('greenhouse_temperature_c','mean'),('cpu_load_percent','mean'),('bridge_uptime_hours','last'),('storage_usage_percent','mean'),('ram_usage_percent','mean'),('power_consumption_w','mean'),('process_count','mean'),('bridge_data_age_s','mean'),('voltage_v','mean'),('current_a','mean'),('signal_min','min'),('signal_max','max'))
def bucket_series(rows,now,hours,step_minutes):
 """Aggregate [(time, {field: value})] into fixed time buckets: mean, max or last value per field."""
 start=now-timedelta(hours=hours);step=step_minutes*60;buckets={}
 for stamp,values in rows:
  if stamp<start or stamp>now:continue
  buckets.setdefault(int(stamp.timestamp()//step),[]).append(values)
 out={'t':[]}
 for field,_ in GRAPH_FIELDS:out[field]=[]
 for key in sorted(buckets):
  group=buckets[key];out['t'].append(datetime.fromtimestamp(key*step+step/2,timezone.utc).isoformat())
  for field,how in GRAPH_FIELDS:
   vals=[v[field] for v in group if v.get(field) is not None]
   out[field].append(None if not vals else round(max(vals) if how=='max' else min(vals) if how=='min' else vals[-1] if how=='last' else sum(vals)/len(vals),3 if field=='current_a' else 2))
 return out
DAILY_KEEP=4200
DAILY_EXTRA=('pressure_max_hpa','pressure_min_hpa','wind_gust_mph','temp_avg_c','humidity_max','humidity_min','dew_max_c','dew_min_c','pressure_avg_hpa','wind_avg_mph','wind_chill_min_c','heat_index_max_c','solar_max_wm2','uv_max','sunshine_hours','cpu_load_avg','uptime_last','storage_usage_avg','ram_usage_avg','power_consumption_avg','process_count_avg','data_age_avg','voltage_avg','current_avg','signal_min','signal_max')
def graph_data(now,wseries,scene,days,history=None,archive=None,local_daily=None):
 """Chart data for 24 h, 7 days, the current calendar month and daily history."""
 live=[(dt(p.get('t')),{k:num(p.get(k)) for k,_ in GRAPH_FIELDS}) for p in wseries or []]
 live=[(t,v) for t,v in live if t]
 hist=[(r['t'],{**{k:r.get(k) for k,_ in GRAPH_FIELDS},'rain_rate_mm_h':r.get('rain_rate_mm_h')}) for r in scene]
 merged={d:dict(v) for d,v in days.items()}
 sources=list((local_daily or {}).items())+[(str(r['date'])[:10],r) for r in (history or {}).get('daily') or [] if isinstance(r,dict) and r.get('date')]+list((archive or {}).items())
 for day,row in sources:
  entry=merged.setdefault(day,{})
  for key in ('temp_max_c','temp_min_c','rain_mm','humidity_avg','rain_max_mm_h')+DAILY_EXTRA:
   if entry.get(key) is None and num(row.get(key)) is not None:entry[key]=num(row.get(key))
 daily=[{'date':d,**{k:s.get(k) for k in ('temp_max_c','temp_min_c','humidity_avg','rain_max_mm_h','rain_mm')+DAILY_EXTRA}} for d,s in sorted(merged.items())[-DAILY_KEEP:]]
 month=[(t,v) for t,v in hist if t>=month_start(now)]
 month_hours=(now-month_start(now)).total_seconds()/3600
 return {'24h':bucket_series(live,now,24,5),'7d':bucket_series(hist,now,168,60),'30d':bucket_series(hist,now,720,180),'month':bucket_series(month,now,month_hours,180),'daily':daily}
