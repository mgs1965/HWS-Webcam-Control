# Telemetry analytics and forecasting helpers (included into dashboard.py).
def quality_summary(rows,now):
 def summarise(label,items):
  pts=[(num(r.get('image_quality_score')),r['_ts']) for r in items]
  pts=[(v,t) for v,t in pts if v is not None]
  if not pts:return {'label':label,'samples':0,'best':None,'worst':None,'average':None}
  best=max(pts,key=lambda x:x[0]);worst=min(pts,key=lambda x:x[0])
  return {'label':label,'samples':len(pts),'average':round(sum(v for v,_ in pts)/len(pts),1),
   'best':{'value':round(best[0],1),'time':best[1].isoformat()},'worst':{'value':round(worst[0],1),'time':worst[1].isoformat()}}
 out=[summarise('Last 24 hours',[r for r in rows if r.get('_ts') and r['_ts']>=now-timedelta(hours=24)])]
 for back in range(1,7):
  day=(now-timedelta(days=back)).date()
  items=[r for r in rows if r.get('_ts') and r['_ts'].date()==day]
  if items:out.append(summarise(day.isoformat(),items))
 return out
def mode_effectiveness(rows,now):
 cut=now-timedelta(hours=24); samples=[]
 for r in rows:
  t=r.get('_ts');m=str(r.get('camera_mode') or r.get('mode') or '').upper()
  if t and cut<=t<=now and m:
   samples.append((t,m,r))
 samples.sort(key=lambda sample:sample[0])
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
  out[m]['sample_status']='NO DATA' if out[m]['samples']==0 else 'LIMITED' if out[m]['samples']<10 else 'SAMPLED'
 transitions=[]
 for t,m,r in samples:
  if not transitions or transitions[-1]['mode']!=m:transitions.append({'timestamp':t.isoformat(),'mode':m})
 return {'window_hours':24,'modes':out,'transitions':transitions[-12:],'sample_count':len(samples),'note':'Descriptive averages only; modes with fewer than 10 captures are marked limited. Time in each mode is estimated between captures and capped at 30 minutes per sample.'}

def disk_forecast(rows,now):
 points=[(r['_ts'],num(get(r,'storage.used_percent'))) for r in rows if r.get('_ts') and r['_ts']>=now-timedelta(days=7)]
 points=[(t,v) for t,v in points if v is not None]
 if len(points)<20 or (points[-1][0]-points[0][0])<timedelta(days=2):return None
 half=len(points)//2;first=sum(v for _,v in points[:half])/half;last=sum(v for _,v in points[half:])/(len(points)-half)
 span=((points[half:][len(points[half:])//2][0])-(points[:half][half//2][0])).total_seconds()/86400
 slope=(last-first)/span if span>0 else 0;used=points[-1][1]
 return {'used_percent':round(used,2),'percent_per_day':round(slope,3),'days_to_full':round((100-used)/slope) if slope>0.005 else None}
def day_calendar(reports,days=35):
 by_date={str(row.get('date'))[:10]:row for row in reports};today=datetime.now(timezone.utc).date();out=[]
 for offset in range(days-1,-1,-1):
  day=today-timedelta(days=offset);row=by_date.get(day.isoformat());video=ROOT/'timelapse'/f'timelapse_{day:%Y%m%d}.mp4'
  try:size=round(video.stat().st_size/1048576,1)
  except OSError:size=None
  out.append({'date':day.isoformat(),'health':row.get('overall') if row else None,'captures':num(row.get('captures')) if row else None,
   'completeness':num(row.get('capture_completeness_percent')) if row else None,'timelapse_mb':size})
 return out
