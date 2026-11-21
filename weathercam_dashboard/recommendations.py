# Operator recommendations (included into dashboard.py).
def recommended_checks(metrics,timelapse,scene=None):
 checks=[]
 if metrics['capture_state'] in ('WARNING','CRITICAL','UNKNOWN'):
  checks.append({'issue':'Capture stream','action':'Check the camera service and the timestamp of the latest capture.'})
 if metrics['ftp_health'] in ('OUTAGE','DEGRADED','RECOVERING'):
  checks.append({'issue':'Image publishing','action':'Check network reachability and the configured FTP destination.'})
 if metrics['control_health'] in ('UNHEALTHY','FAILED','DEGRADED'):
  checks.append({'issue':'Camera control','action':'Review recent control acknowledgements and camera-mode events.'})
 if metrics['disk_free_gb'] is not None and metrics['disk_free_gb']<TH['disk_free_warning_gb']:
  checks.append({'issue':'Storage','action':'Review free space and the configured retention/cleanup policy.'})
 if metrics['cpu_temp_c'] is not None and metrics['cpu_temp_c']>=TH['cpu_temp_warning_c']:
  checks.append({'issue':'Temperature','action':'Check Raspberry Pi cooling, ventilation and workload.'})
 if metrics['memory_percent'] is not None and metrics['memory_percent']>=TH['memory_warning_percent']:
  checks.append({'issue':'Memory','action':'Review memory history and running processes on the Raspberry Pi.'})
 if metrics['throttling_active'] is True:
  checks.append({'issue':'Power or thermal throttling','action':'Check the Pi power supply, cooling and active load.'})
 if metrics['health_age_seconds'] is None or metrics['health_age_seconds']>TH['health_stale_seconds']:
  checks.append({'issue':'Health data','action':'Confirm the camera service is recording system-health snapshots.'})
 if timelapse and timelapse['source_gap_count']:
  checks.append({'issue':'Timelapse gaps','action':'Review the missing-hour details in the latest daily report.'})
 alerts=set((scene or {}).get('alerts') or [])
 for name,issue,action in (('FROZEN_IMAGE','Frozen image','Frames are not changing; check the camera, cable and service.'),('BLOCKED_VIEW','Blocked view','The view looks obstructed; inspect the lens and housing.'),('LENS_DROPLETS','Lens droplets','Droplets suspected on the lens or dome; clean it when safe.'),('FOG','Fog or haze','Persistent fog reduces image clarity; check the lens for condensation.'),('FOCUS_DRIFT','Focus drift','Sharpness is declining; check lens focus and cleanliness.')):
  if name in alerts:checks.append({'issue':issue,'action':action})
 return checks
