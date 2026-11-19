"""V47.1 control acknowledgement, health and transition validation subsystem."""
from collections import deque

CONTROL_HISTORY_DEPTH = 6
CONTROL_HISTORY_EXPIRY_SECONDS = 90
CONTROL_ACK_EXTENDED_CAPTURES = 6
CONTROL_HEALTH_WINDOW_SECONDS = 1800
CONTROL_HEALTH_MINIMUM_SAMPLES = 6
CONTROL_REPEATED_TIMEOUT_WINDOW_SECONDS = 900
MODE_VALIDATION_CAPTURES = 6
MODE_VALIDATION_MAX_HIGHLIGHTS_PERCENT = 5.0

control_sequence_id = 0
control_history = deque(maxlen=CONTROL_HISTORY_DEPTH)
control_ack_samples = deque(maxlen=256)
control_ack_state = 'IDLE'
control_exposure_acknowledged = True
control_gain_acknowledged = True
control_matched_history_depth = None
control_last_ack_latency_seconds = None
control_pipeline_lag_count = 0
control_timeout_count = 0
control_reconciliation_count = 0
control_superseded_count = 0
control_timeout_times = deque(maxlen=32)
control_health = 'LEARNING'
control_health_reason = 'Startup validation 0/6 captures'
control_health_established = False
control_startup_validation_captures = 0
control_successful_ack_count = 0
control_last_successful_ack_time = None
control_ack_p95_captures = 0
mode_validation = None


def _control_now(): return local_now()
def _within(e,g,r): return abs(e-r['exposure_us']) <= CONTROL_ACK_EXPOSURE_TOLERANCE_US and abs(g-r['gain']) <= CONTROL_ACK_GAIN_TOLERANCE


def submit_control(exposure_us, gain, reason, mode=None):
    global control_sequence_id, control_ack_state, control_superseded_count
    now=_control_now()
    if control_history and control_history[-1]['state'] in ('SUBMITTED','PIPELINE_LAG'):
        control_history[-1]['state']='SUPERSEDED'; control_history[-1]['closed_at']=now; control_superseded_count+=1
        logger.info('[CONTROL SUPERSEDED] Id=%d | ReplacedBy=%d',control_history[-1]['id'],control_sequence_id+1)
    control_sequence_id+=1
    item={'id':control_sequence_id,'submitted_at':now,'capture_count':0,'exposure_us':int(exposure_us),'gain':float(gain),'reason':str(reason),'mode':mode or current_camera_mode,'state':'SUBMITTED'}
    control_history.append(item); control_ack_state='SUBMITTED'
    logger.info('[CONTROL SUBMIT] Id=%d | Mode=%s | Reason=%s | Exp=%.0fms G%.2f',item['id'],item['mode'],item['reason'],item['exposure_us']/1000,item['gain'])
    return item['id']


def evaluate_control_ack(actual_exposure, actual_gain):
    global control_ack_state,control_exposure_acknowledged,control_gain_acknowledged,control_matched_history_depth
    global control_last_ack_latency_seconds,control_pipeline_lag_count,control_timeout_count,control_reconciliation_count
    global control_successful_ack_count,control_last_successful_ack_time
    now=_control_now()
    if not control_history: return {'state':'IDLE','waiting':False,'timeout':False,'exposure_ack':True,'gain_ack':True,'captures':0}
    current=control_history[-1]; current['capture_count']+=1
    control_exposure_acknowledged=abs(actual_exposure-current['exposure_us'])<=CONTROL_ACK_EXPOSURE_TOLERANCE_US
    control_gain_acknowledged=abs(actual_gain-current['gain'])<=CONTROL_ACK_GAIN_TOLERANCE
    if control_exposure_acknowledged and control_gain_acknowledged:
        current['state']='ACKNOWLEDGED'; control_ack_state='ACKNOWLEDGED'; control_matched_history_depth=0
        control_last_ack_latency_seconds=max(0,(now-current['submitted_at']).total_seconds()); control_ack_samples.append((now,current['capture_count'])); control_successful_ack_count+=1; control_last_successful_ack_time=now
        logger.info('[CONTROL ACK] Id=%d | State=ACKNOWLEDGED | AppliedAfter=%d captures | Latency=%.1fs | Exposure=ACK | Gain=ACK',current['id'],current['capture_count'],control_last_ack_latency_seconds)
        update_control_health(); return {'state':control_ack_state,'waiting':False,'timeout':False,'exposure_ack':True,'gain_ack':True,'captures':current['capture_count']}
    for depth,request in enumerate(reversed(list(control_history)[:-1]),1):
        if (now-request['submitted_at']).total_seconds()<=CONTROL_HISTORY_EXPIRY_SECONDS and _within(actual_exposure,actual_gain,request):
            if current.get('last_lag_match')!=request['id']: control_pipeline_lag_count+=1; current['last_lag_match']=request['id']
            current['state']='PIPELINE_LAG'; control_ack_state='PIPELINE_LAG'; control_matched_history_depth=depth
            logger.info('[CONTROL ACK] Id=%d | State=PIPELINE_LAG | MatchedId=%d | HistoryDepth=%d | Capture=%d/%d',current['id'],request['id'],depth,current['capture_count'],CONTROL_ACK_EXTENDED_CAPTURES)
            return {'state':control_ack_state,'waiting':current['capture_count']<CONTROL_ACK_EXTENDED_CAPTURES,'timeout':False,'exposure_ack':control_exposure_acknowledged,'gain_ack':control_gain_acknowledged,'captures':current['capture_count']}
    if current['capture_count']<CONTROL_ACK_EXTENDED_CAPTURES:
        control_ack_state='SUBMITTED'; return {'state':control_ack_state,'waiting':True,'timeout':False,'exposure_ack':control_exposure_acknowledged,'gain_ack':control_gain_acknowledged,'captures':current['capture_count']}
    current['state']='TIMEOUT'; control_ack_state='TIMEOUT'; control_timeout_count+=1; control_reconciliation_count+=1; control_timeout_times.append(now); control_ack_samples.append((now,current['capture_count']))
    logger.warning('[CONTROL ACK] Id=%d | State=TIMEOUT | Captures=%d | Exposure=%s | Gain=%s | Reconciling',current['id'],current['capture_count'],'ACK' if control_exposure_acknowledged else 'MISS','ACK' if control_gain_acknowledged else 'MISS')
    update_control_health(); return {'state':control_ack_state,'waiting':False,'timeout':True,'exposure_ack':control_exposure_acknowledged,'gain_ack':control_gain_acknowledged,'captures':current['capture_count']}


def update_control_health(observe_capture=False):
    global control_health,control_health_reason,control_ack_p95_captures
    global control_health_established,control_startup_validation_captures
    now=_control_now(); pending=control_history and control_history[-1]['state'] in ('SUBMITTED','PIPELINE_LAG')
    if observe_capture and not pending and not control_health_established:
        control_startup_validation_captures=min(CONTROL_HEALTH_MINIMUM_SAMPLES,control_startup_validation_captures+1)
        if control_startup_validation_captures>=CONTROL_HEALTH_MINIMUM_SAMPLES: control_health_established=True
    samples=[c for t,c in control_ack_samples if (now-t).total_seconds()<=CONTROL_HEALTH_WINDOW_SECONDS]
    if samples:
        o=sorted(samples); control_ack_p95_captures=o[max(0,int(round(.95*(len(o)-1))))]
    if not control_health_established and control_successful_ack_count<CONTROL_HEALTH_MINIMUM_SAMPLES:
        control_health='VALIDATING'; control_health_reason=f'Startup validation {control_startup_validation_captures}/{CONTROL_HEALTH_MINIMUM_SAMPLES} captures; ACKs={control_successful_ack_count}'; return
    control_health_established=True
    recent=sum(1 for t in control_timeout_times if (now-t).total_seconds()<=CONTROL_REPEATED_TIMEOUT_WINDOW_SECONDS)
    if recent>=2 or (samples and control_ack_p95_captures>6): control_health='UNHEALTHY'
    elif recent or (samples and control_ack_p95_captures>=4): control_health='DEGRADED'
    elif pending: control_health='HEALTHY'
    elif control_last_successful_ack_time is None or (now-control_last_successful_ack_time).total_seconds()>CONTROL_HEALTH_WINDOW_SECONDS: control_health='IDLE'
    else: control_health='HEALTHY'
    control_health_reason=f'{recent} timeout(s)/15m; ACK p95={control_ack_p95_captures}; successful={control_successful_ack_count}; pending={bool(pending)}'


def control_status_fields(now=None):
    update_control_health(observe_capture=True)
    now=now or _control_now(); pending=control_history[-1] if control_history and control_history[-1]['state'] in ('SUBMITTED','PIPELINE_LAG') else None
    return {'control_pending':bool(pending),'control_pending_id':pending['id'] if pending else None,'control_pending_age_seconds':round((now-pending['submitted_at']).total_seconds(),1) if pending else 0,'control_last_ack_latency_seconds':control_last_ack_latency_seconds,'control_ack_state':control_ack_state,'control_health':control_health,'control_health_reason':control_health_reason,'control_ack_p95_captures':control_ack_p95_captures,'control_pipeline_lag_count':control_pipeline_lag_count,'control_timeout_count':control_timeout_count,'control_reconciliation_count':control_reconciliation_count,'control_superseded_count':control_superseded_count,'control_successful_ack_count':control_successful_ack_count,'control_health_established':control_health_established,'control_startup_validation_captures':control_startup_validation_captures,'last_control_timeout_time':control_timeout_times[-1].isoformat() if control_timeout_times else None}


def arm_mode_validation(previous_mode,new_mode,brightness,highlights,exposure_us,gain):
    global mode_validation
    mode_validation={'kind':'STARTUP' if previous_mode is None else 'MODE','from':previous_mode,'to':new_mode,'capture':0,'brightness_start':float(brightness),'highlights_max':float(highlights),'reversal':False}


def update_mode_validation(measurement,exposure_us,gain):
    global mode_validation
    if not mode_validation: return
    try:
        brightness=float(measurement.get('brightness',0.0)); highlights=float(measurement.get('highlights',0.0))
        mode_validation['capture']+=1; mode_validation['highlights_max']=max(mode_validation['highlights_max'],highlights)
        if mode_validation['from'] is not None and current_camera_mode==mode_validation['from']: mode_validation['reversal']=True
        label='STARTUP VALIDATION' if mode_validation['kind']=='STARTUP' else 'MODE VALIDATION'
        if mode_validation['capture'] in (3,MODE_VALIDATION_CAPTURES):
            logger.info('[%s] %s -> %s | Capture=%d | B %.1f->%.1f | HighlightsMax=%.2f%% | Ack=%s | Reversal=%s',label,mode_validation['from'] or 'START',mode_validation['to'],mode_validation['capture'],mode_validation['brightness_start'],brightness,mode_validation['highlights_max'],control_ack_state,mode_validation['reversal'])
        if mode_validation['capture']>=MODE_VALIDATION_CAPTURES:
            result='FAILED' if mode_validation['reversal'] or mode_validation['highlights_max']>=MODE_VALIDATION_MAX_HIGHLIGHTS_PERCENT else 'PASSED'
            logger.info('[%s] %s -> %s | Result=%s | B %.1f->%.1f | HighlightsMax=%.2f%% | Reversal=%s',label,mode_validation['from'] or 'START',mode_validation['to'],result,mode_validation['brightness_start'],brightness,mode_validation['highlights_max'],mode_validation['reversal'])
            mode_validation=None
    except Exception:
        logger.exception('[MODE VALIDATION] Internal failure; validation cancelled to protect capture cycle')
        mode_validation=None
