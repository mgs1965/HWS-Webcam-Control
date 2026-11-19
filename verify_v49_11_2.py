#!/usr/bin/env python3
import ast,json,os,re,subprocess,tempfile
from datetime import datetime,timezone,timedelta
from pathlib import Path
from shutil import which as shutil_which
r=Path(__file__).parent
mods=['version.py','core.py','camera.py','modes.py','exposure.py','v47_control.py','image_quality.py','state.py','controller_analytics.py','publishing.py','timelapse.py','monitoring.py','runtime.py','loader.py','weather_camera.py','weathercam_dashboard/dashboard.py']
for f in mods:compile((r/f).read_text(),str(r/f),'exec')
ns={};exec((r/'version.py').read_text(),ns);assert ns['VERSION']=='V49.11.2' and ns['TELEMETRY_SCHEMA_VERSION']==4
assert "SCRIPT_VERSION = '2026-11-18 V49.11.2'" in (r/'core.py').read_text()
m=ast.parse((r/'publishing.py').read_text());a=next(n for n in m.body if isinstance(n,ast.Assign) and any(getattr(t,'id','')=='TELEMETRY_FIELDS' for t in n.targets));assert len(ast.literal_eval(a.value))==58
analytics=(r/'controller_analytics.py').read_text();camera=(r/'camera.py').read_text();py=(r/'weathercam_dashboard/dashboard.py').read_text();ht=(r/'weathercam_dashboard/templates/dashboard.html').read_text()
assert 'Path(' not in analytics and 'ANALYTICS_MIN_FREE_SPACE_GB = 5.0' in analytics
assert 'with open(path' in analytics and 'os.fsync(target.fileno())' in analytics
assert "capture cycle will continue" in camera
assert "V='49.11.2'" in py and "'release':'V49.11.2'" in py
for v in ['live','24h','7d','30d','controller','gallery','diagnostics']:assert f'data-view="{v}"' in ht and f'id="{v}"' in ht,v
assert 'const fmtTime=value=>' in ht and "try{renderController()}catch(error)" in ht
assert ht.index('function show(v)') < ht.index('function renderController()')
# Execute analytics against the symbols available from core/shared runtime, with no Path injection.
with tempfile.TemporaryDirectory() as d:
 g={'os':os,'json':json,'hashlib':__import__('hashlib'),'datetime':__import__('datetime').datetime,'defaultdict':__import__('collections').defaultdict,'deque':__import__('collections').deque,'LOGS_PATH':d,'VERSION':'V49.11.2','current_camera_mode':'DAY','current_solar_elevation':5.0,'control_health':'HEALTHY','ftp_consecutive_failures':0,'get_free_space_gb':lambda:100.0,'DAY_MAX_EXPOSURE_US':1000,'TWILIGHT_MAX_EXPOSURE_US':2000,'LOW_LIGHT_MAX_EXPOSURE_US':1500000,'NIGHT_MAX_EXPOSURE_US':2000000,'MIN_ANALOGUE_GAIN':1.0,'ABSOLUTE_MAX_GAIN':8.0}
 exec(analytics,g)
 for i in range(3):
  now=datetime.now(timezone.utc)+timedelta(seconds=i);g['record_controller_analytics'](now,{'ExposureTime':1000,'AnalogueGain':1.0},{'brightness':50,'filtered_brightness':50,'controller_target_brightness':50,'controller_error':0,'controller_decision':'HOLD_DEADBAND','controller_next_exposure_ms':1,'image_quality_score':90,'sharpness_score':10,'contrast':20,'image_quality_status':'STABLE'})
 assert Path(d,'controller_analytics.json').exists();assert len(Path(d,'controller_history.jsonl').read_text().splitlines())==3
# Dashboard generation with an event ensures fmtTime path is present in rendered output.
with tempfile.TemporaryDirectory() as d:
 root=Path(d);(root/'logs').mkdir();(root/'telemetry/health').mkdir(parents=True);(root/'frames').mkdir();now=datetime.now(timezone.utc).isoformat();(root/'frames/latest.jpg').write_bytes(b'jpeg');(root/'frames/frame_test.jpg').write_bytes(b'jpeg')
 status={'capture_time':now,'camera_mode':'NIGHT','ftp_health_state':'HEALTHY','ftp_last_success_time':now,'ftp_consecutive_failures':0,'ftp_worker_alive':True,'control_health':'HEALTHY','uptime_seconds':60,'exposure_seconds':1.2,'analogue_gain':1.0,'filtered_brightness':38,'image_quality_score':90,'sharpness_score':2,'camera_restart_count':0,'controller_decision':'HOLD_DEADBAND','learning_mode':'NIGHT','software_version':'V49.11.2','telemetry_schema_version':4};(root/'logs/camera_status.json').write_text(json.dumps(status));(root/'logs/controller_analytics.json').write_text(json.dumps({'release':'V49.11.2','health_score':{'overall':100},'limits':{},'mode_learning':{},'anomalies':[]}));(root/'logs/controller_events.jsonl').write_text(json.dumps({'timestamp':now,'message':'NIGHT active'})+'\n');(root/'logs/controller_history.jsonl').write_text('{}\n')
 q=subprocess.run(['python3',str(r/'weathercam_dashboard/dashboard.py')],env={**os.environ,'WEATHERCAM_ROOT':d},capture_output=True,text=True);assert q.returncode==0,q.stderr
 out=(root/'dashboard/dashboard.html').read_text();assert '__DATA__' not in out and 'V49.11.2' in out and 'NIGHT active' in out
 # JS syntax verification via Node when available.
 scripts=re.findall(r'<script>(.*?)</script>',out,re.S);assert scripts
 js=Path(d,'dashboard-runtime.js');js.write_text('\n'.join(scripts))
 node=subprocess.run(['node','--check',str(js)],capture_output=True,text=True) if shutil_which('node') else None
 if node is not None:assert node.returncode==0,node.stderr
print('PASS: V49.11.2 compilation and release identity')
print('PASS: telemetry-v4 immutable 58-field contract')
print('PASS: analytics retention runs without pathlib.Path')
print('PASS: three-record retention execution test')
print('PASS: defensive fmtTime formatter present')
print('PASS: navigation initialises before optional Controller renderer')
print('PASS: Controller rendering isolated from navigation')
print('PASS: generated seven-view dashboard with controller event')
