# Sun, moon and camera-mode schedule helpers (included into dashboard.py).
MODE_NAMES=('NIGHT','LOW LIGHT','TWILIGHT','DAY')
MODE_BOUNDARIES=(-5.0,-1.5,0.5)
MODE_HYSTERESIS=0.25
SYNODIC_MONTH=29.530588853
def sun_times(day):
 n=day.timetuple().tm_yday;g=2*math.pi/365*(n-1);lat=math.radians(LATITUDE)
 eq=229.18*(0.000075+0.001868*math.cos(g)-0.032077*math.sin(g)-0.014615*math.cos(2*g)-0.040849*math.sin(2*g))
 decl=0.006918-0.399912*math.cos(g)+0.070257*math.sin(g)-0.006758*math.cos(2*g)+0.000907*math.sin(2*g)-0.002697*math.cos(3*g)+0.00148*math.sin(3*g)
 cos_ha=math.cos(math.radians(90.833))/(math.cos(lat)*math.cos(decl))-math.tan(lat)*math.tan(decl)
 if abs(cos_ha)>1:return None
 ha=math.degrees(math.acos(cos_ha));midnight=datetime(day.year,day.month,day.day,tzinfo=timezone.utc)
 return (midnight+timedelta(minutes=720-4*(LONGITUDE+ha)-eq),midnight+timedelta(minutes=720-4*(LONGITUDE-ha)-eq))
def sun_events(now,days=30):
 out=[];start=(now-timedelta(days=days)).date()
 for offset in range(days+2):
  times=sun_times(start+timedelta(days=offset))
  if not times:continue
  for kind,stamp in zip(('sunrise','sunset'),times):
   if now-timedelta(days=days)<=stamp<=now:out.append({'time':stamp.isoformat(),'type':kind})
 return out
def solar_elevation(when):
 when=when.astimezone(timezone.utc);n=when.timetuple().tm_yday;hour=when.hour+when.minute/60+when.second/3600
 g=2*math.pi/365*(n-1+(hour-12)/24)
 eq=229.18*(0.000075+0.001868*math.cos(g)-0.032077*math.sin(g)-0.014615*math.cos(2*g)-0.040849*math.sin(2*g))
 decl=0.006918-0.399912*math.cos(g)+0.070257*math.sin(g)-0.006758*math.cos(2*g)+0.000907*math.sin(2*g)-0.002697*math.cos(3*g)+0.00148*math.sin(3*g)
 angle=((hour*60+eq+4*LONGITUDE)%1440)/4-180;lat=math.radians(LATITUDE)
 cosz=math.sin(lat)*math.sin(decl)+math.cos(lat)*math.cos(decl)*math.cos(math.radians(angle))
 return 90-math.degrees(math.acos(max(-1,min(1,cosz))))
def mode_stage(elevation,previous,rising):
 stage=previous
 if rising:
  while stage<3 and elevation>=MODE_BOUNDARIES[stage]+MODE_HYSTERESIS:stage+=1
 else:
  while stage>0 and elevation<MODE_BOUNDARIES[stage-1]-MODE_HYSTERESIS:stage-=1
 return stage
def mode_schedule(now,back_hours=24,forward_hours=24):
 """Predicted solar-elevation mode changes, using the controller boundaries and hysteresis."""
 start=now-timedelta(hours=back_hours);steps=(back_hours+forward_hours)*60
 elevation=solar_elevation(start);stage=sum(elevation>=b for b in MODE_BOUNDARIES);out=[];previous=elevation
 for minute in range(1,steps+1):
  moment=start+timedelta(minutes=minute);elevation=solar_elevation(moment)
  new=mode_stage(elevation,stage,elevation>=previous);previous=elevation
  if new!=stage:out.append({'time':moment.isoformat(),'from':MODE_NAMES[stage],'to':MODE_NAMES[new],'elevation':round(elevation,2)});stage=new
 return out
def next_mode_change(now,schedule):
 for item in schedule:
  stamp=dt(item['time'])
  if stamp and stamp>now:return dict(item,minutes=int((stamp-now).total_seconds()//60))
 return None
def moon_phase(now):
 reference=datetime(2000,1,6,18,14,tzinfo=timezone.utc);age=((now-reference).total_seconds()/86400)%SYNODIC_MONTH
 illumination=(1-math.cos(2*math.pi*age/SYNODIC_MONTH))/2*100
 names=('New moon','Waxing crescent','First quarter','Waxing gibbous','Full moon','Waning gibbous','Last quarter','Waning crescent')
 name=names[int((age/SYNODIC_MONTH*8+0.5)%8)]
 next_full=(SYNODIC_MONTH/2-age)%SYNODIC_MONTH;next_new=(SYNODIC_MONTH-age)%SYNODIC_MONTH
 return {'phase':name,'illumination_percent':round(illumination,1),'age_days':round(age,1),'next_full':(now+timedelta(days=next_full)).date().isoformat(),'next_new':(now+timedelta(days=next_new)).date().isoformat()}
def sun_moon(now):
 times=sun_times(now.date());out={'moon':moon_phase(now),'elevation':round(solar_elevation(now),2)}
 if times:
  rise,sset=times
  out.update({'sunrise':rise.isoformat(),'sunset':sset.isoformat(),'solar_noon':(rise+(sset-rise)/2).isoformat(),'day_length_seconds':int((sset-rise).total_seconds()),
   'golden_morning_end':(rise+timedelta(hours=1)).isoformat(),'golden_evening_start':(sset-timedelta(hours=1)).isoformat()})
 return out
