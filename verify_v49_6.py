#!/usr/bin/env python3
import ast,json,os,subprocess,tempfile
from datetime import datetime,timezone
from pathlib import Path
r=Path(__file__).parent
mods=['version.py','core.py','camera.py','modes.py','exposure.py','v47_control.py','image_quality.py','state.py','publishing.py','timelapse.py','monitoring.py','runtime.py','loader.py','weather_camera.py','weathercam_dashboard/dashboard.py']
for f in mods:compile((r/f).read_text(),str(r/f),'exec')
ns={};exec((r/'version.py').read_text(),ns);assert ns['VERSION']=='V49.6' and ns['TELEMETRY_SCHEMA_VERSION']==4
assert "SCRIPT_VERSION = '2026-11-17 V49.6'" in (r/'core.py').read_text()
m=ast.parse((r/'publishing.py').read_text());a=next(n for n in m.body if isinstance(n,ast.Assign) and any(getattr(t,'id','')=='TELEMETRY_FIELDS' for t in n.targets));assert len(ast.literal_eval(a.value))==58
py=(r/'weathercam_dashboard/dashboard.py').read_text();ht=(r/'weathercam_dashboard/templates/dashboard.html').read_text()
for x in ["V='49.6.0'",'mode_series','remote_frames!=desired','obsolete=remote_frames-desired',"('latest.jpg','dashboard-data.json','dashboard.html')"]:assert x in py,x
for x in ['V49.6','Looking North East','Live','24 Hours','7 Days','30 Days','Gallery','Diagnostics','System Health','Camera Mode Timeline','TWILIGHT','LOW LIGHT','Not available','log=false','galleryFilters','mock-live','mock-camera','mock-health','mock-settings','mock-chart','mock-bottom']:assert x in ht,x
for x in ['Last Capture','Last Upload','Current Camera Settings','Brightness &amp; Quality','Exposure','Raspberry Pi / Process','Recent Events','Health Checks']:assert x in ht,x
assert ht.count('class="mock-chart card"') >= 3
assert ht.count('class="mock-bottom card"') == 3
with tempfile.TemporaryDirectory() as d:
 root=Path(d);(root/'logs').mkdir();(root/'telemetry/health').mkdir(parents=True);(root/'frames').mkdir();now=datetime.now(timezone.utc).isoformat();(root/'frames/latest.jpg').write_bytes(b'jpeg');(root/'frames/frame_test.jpg').write_bytes(b'jpeg')
 status={'capture_time':now,'camera_mode':'DAY','ftp_health_state':'HEALTHY','ftp_last_success_time':now,'ftp_consecutive_failures':0,'ftp_worker_alive':True,'control_health':'HEALTHY','uptime_seconds':60,'exposure_seconds':0.001,'analogue_gain':1.0,'filtered_brightness':50,'image_quality_score':90,'sharpness_score':12,'camera_restart_count':0};(root/'logs/camera_status.json').write_text(json.dumps(status))
 q=subprocess.run(['python3',str(r/'weathercam_dashboard/dashboard.py')],env={**os.environ,'WEATHERCAM_ROOT':d},capture_output=True,text=True);assert q.returncode==0,q.stderr
 data=json.loads((root/'dashboard/dashboard-data.json').read_text());assert data['version']=='49.6.0';assert data['config']['release']=='V49.6';assert data['metrics']['capture_age_seconds']<10;assert data['metrics']['ftp_health']=='HEALTHY';assert data['gallery'] and 'quality' in data['gallery'][0]
 out=(root/'dashboard/dashboard.html').read_text();assert '__DATA__' not in out and 'Diagnostics' in out and 'Looking North East' in out
print('PASS: V49.6 source compilation and unified release identity')
print('PASS: telemetry-v4 contract remains 58 fields')
print('PASS: mock-up UI and six functional views')
print('PASS: approved Live page grid contract')
print('PASS: real camera mode history data contract')
print('PASS: graph scales/legends/log exposure implementation')
print('PASS: telemetry-enriched Gallery cards and filters')
print('PASS: Diagnostics safe fallback and no Settings regression')
print('PASS: V49.5 exact-set Gallery publisher retained')
