"""V49.11 controller analytics, persistence and anomaly intelligence."""
from collections import defaultdict, deque
CONTROLLER_HISTORY_FILE=os.path.join(LOGS_PATH,'controller_history.jsonl')
CONTROLLER_SUMMARY_FILE=os.path.join(LOGS_PATH,'controller_analytics.json')
CONTROLLER_EVENTS_FILE=os.path.join(LOGS_PATH,'controller_events.jsonl')
ANALYTICS_MIN_FREE_SPACE_GB = 5.0
_controller_windows=deque(maxlen=10080)
_mode_baselines=defaultdict(lambda: defaultdict(lambda: deque(maxlen=2016)))
_limit_windows={'exposure':deque(maxlen=180),'gain':deque(maxlen=180)}
_last_analytics_mode=None
_last_analytics_health=None

def _median(values):
    vals=sorted(float(v) for v in values if v is not None)
    if not vals:return None
    n=len(vals);return vals[n//2] if n%2 else (vals[n//2-1]+vals[n//2])/2.0

def _atomic_json(path,data):
    tmp=path+'.tmp'
    with open(tmp,'w',encoding='utf-8') as f:json.dump(data,f,indent=2,sort_keys=True)
    os.replace(tmp,path)

def _append_jsonl(path,data):
    with open(path,'a',encoding='utf-8') as f:f.write(json.dumps(data,sort_keys=True,separators=(',',':'))+'\n')

def _event(ts,kind,message,severity='INFO',details=None):
    _append_jsonl(CONTROLLER_EVENTS_FILE,{'timestamp':ts,'kind':kind,'severity':severity,'message':message,'details':details or {}})

def _pct(q):return round(100.0*sum(bool(x) for x in q)/len(q),1) if q else 0.0

def record_controller_analytics(capture_time,metadata,measurement):
    global _last_analytics_mode,_last_analytics_health
    ts=capture_time.isoformat();mode=current_camera_mode
    rec={'timestamp':ts,'mode':mode,'brightness':measurement.get('filtered_brightness',measurement.get('brightness')),'target':measurement.get('controller_target_brightness'),'error':measurement.get('controller_error'),'decision':measurement.get('controller_decision','HOLD_STABLE'),'exposure_ms':float(metadata.get('ExposureTime',0))/1000.0,'next_exposure_ms':measurement.get('controller_next_exposure_ms'),'analogue_gain':metadata.get('AnalogueGain'),'quality':measurement.get('image_quality_score'),'sharpness':measurement.get('sharpness_score'),'contrast':measurement.get('contrast'),'exposure_limit':bool(measurement.get('controller_at_exposure_limit_v499')),'gain_limit':bool(measurement.get('controller_at_gain_limit_v499')),'learning_state':'LEARNING' if measurement.get('image_quality_status') in ('LEARNING','SETTLING') else 'STABLE','control_health':control_health}
    _controller_windows.append(rec);_append_jsonl(CONTROLLER_HISTORY_FILE,rec)
    for k in ('brightness','exposure_ms','analogue_gain','quality','sharpness','contrast','error'):_mode_baselines[mode][k].append(rec.get(k))
    _limit_windows['exposure'].append(rec['exposure_limit']);_limit_windows['gain'].append(rec['gain_limit'])
    if _last_analytics_mode and _last_analytics_mode!=mode:_event(ts,'MODE_TRANSITION',f'{_last_analytics_mode} -> {mode}',details={'from':_last_analytics_mode,'to':mode,'solar_elevation':current_solar_elevation})
    if _last_analytics_health and _last_analytics_health!=control_health:_event(ts,'CONTROL_HEALTH',f'Control health {_last_analytics_health} -> {control_health}','WARNING' if control_health!='HEALTHY' else 'INFO')
    _last_analytics_mode=mode;_last_analytics_health=control_health
    anomalies=[];base=_mode_baselines[mode]
    for metric in ('exposure_ms','brightness','quality','sharpness','contrast','error'):
        vals=base[metric];med=_median(vals);cur=rec.get(metric)
        if cur is None or med in (None,0) or len(vals)<30:continue
        delta=(float(cur)-med)/abs(med)*100.0
        threshold=40.0 if metric in ('exposure_ms','error') else 30.0
        if abs(delta)>=threshold:anomalies.append({'metric':metric,'current':round(float(cur),3),'baseline_median':round(med,3),'change_pct':round(delta,1),'severity':'WARNING'})
    exp5=_pct(list(_limit_windows['exposure'])[-30:]);exp30=_pct(_limit_windows['exposure']);gain5=_pct(list(_limit_windows['gain'])[-30:]);gain30=_pct(_limit_windows['gain'])
    limit_state='PERSISTENT' if max(exp30,gain30)>50 else ('CONSTRAINED' if max(exp5,gain5)>50 else ('WATCH' if max(exp5,gain5)>=20 else 'NORMAL'))
    optics_penalty=min(30,sum(10 for a in anomalies if a['metric'] in ('sharpness','contrast','quality')));controller_penalty=min(30,sum(8 for a in anomalies if a['metric'] in ('exposure_ms','error')))+(15 if limit_state in ('CONSTRAINED','PERSISTENT') else 0)
    health={'overall':max(0,100-optics_penalty-controller_penalty),'optics':max(0,100-optics_penalty),'controller':max(0,100-controller_penalty),'publishing':100 if ftp_consecutive_failures==0 else max(0,100-10*ftp_consecutive_failures),'storage':100 if get_free_space_gb() >= ANALYTICS_MIN_FREE_SPACE_GB else 50}
    mode_learning={}
    for m in ('DAY','TWILIGHT','LOW LIGHT','NIGHT'):
        count=len(_mode_baselines[m]['brightness']);required=100
        mode_learning[m]={'samples':count,'required_samples':required,'progress_pct':round(min(100,count*100/required),1),'confidence':'HIGH' if count>=required else ('MEDIUM' if count>=50 else 'LOW'),'state':'STABLE' if count>=required else ('LEARNING' if count else 'INSUFFICIENT_DATA')}
    summary={'release':VERSION,'generated_at':ts,'config_fingerprint':_configuration_fingerprint(),'latest':rec,'limits':{'state':limit_state,'exposure_pct_5m':exp5,'exposure_pct_30m':exp30,'gain_pct_5m':gain5,'gain_pct_30m':gain30},'mode_learning':mode_learning,'anomalies':anomalies[-20:],'health_score':health,'history_count':len(_controller_windows)}
    _atomic_json(CONTROLLER_SUMMARY_FILE,summary)
    _trim_controller_files(capture_time)

def _configuration_fingerprint():
    keys=['MAX_TWILIGHT_EXPOSURE_US','MAX_LOW_LIGHT_EXPOSURE_US','MAX_NIGHT_EXPOSURE_US','MIN_EXPOSURE_US','MIN_ANALOGUE_GAIN','ABSOLUTE_MAX_GAIN']
    raw='|'.join(f'{k}={globals().get(k)}' for k in keys)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]

def _trim_controller_files(now):
    cutoff=now.timestamp()-48*3600
    for path,maxlines in ((CONTROLLER_HISTORY_FILE,20000),(CONTROLLER_EVENTS_FILE,2000)):
        try:
            with open(path,'r',encoding='utf-8') as source:
                lines=source.read().splitlines()[-maxlines:]
            kept=[]
            for line in lines:
                try:
                    row=json.loads(line); t=datetime.fromisoformat(row['timestamp']).timestamp()
                    if path==CONTROLLER_EVENTS_FILE or t>=cutoff:kept.append(line)
                except Exception:pass
            tmp=path+'.tmp'
            with open(tmp,'w',encoding='utf-8') as target:
                target.write(('\n'.join(kept)+'\n') if kept else '')
                target.flush(); os.fsync(target.fileno())
            os.replace(tmp,path)
        except OSError:pass
