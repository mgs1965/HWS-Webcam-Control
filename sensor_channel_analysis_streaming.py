#!/usr/bin/env python3
"""Pi-safe streaming Weather Display sensor-channel analyser v1.3.2.
Constant-memory channel statistics, bounded transitions, checkpoint/resume.
"""
from __future__ import annotations
import argparse,csv,json,re,sys,time
from dataclasses import dataclass,asdict,field
from datetime import datetime
from pathlib import Path
from typing import Optional
VERSION='1.3.2'
SUFFIXES={'vantageextrasensorslog.csv':'vantage_extra_sensors','extralog.csv':'extra_log','growlogten.txt':'grow10'}
DEFAULT_SENTINELS={-100.0,1000.0,-1000.0,2550.0}
def safe(x):return re.sub(r'[^a-z0-9]+','_',str(x).strip().lower()).strip('_') or 'unnamed'
def number(x):
 try:return float(x)
 except:return None
def delim(line):
 if line.count(',')>=2:return ','
 if line.count(';')>=2:return ';'
 if line.count('\t')>=2:return '\t'
 return None
def split(line,d):
 if d==',':return next(csv.reader([line]))
 if d==';':return next(csv.reader([line],delimiter=';'))
 if d=='\t':return line.split('\t')
 return line.split()
def parse_dt(a):
 try:return datetime(int(float(a[2])),int(float(a[1])),int(float(a[0])),int(float(a[3])),int(float(a[4])))
 except:return None
@dataclass
class Stat:
 observations:int=0; numeric_count:int=0; valid_count:int=0; sentinel_count:int=0
 total:float=0.0; minimum:Optional[float]=None; maximum:Optional[float]=None
 first_observation:Optional[str]=None; last_observation:Optional[str]=None
 first_valid:Optional[str]=None; last_valid:Optional[str]=None
 previous_state:Optional[str]=None; state_transition_count:int=0
 transitions:list=field(default_factory=list); transition_overflow:int=0
 def add(self,dt,v,sentinels,max_transitions):
  iso=dt.isoformat();self.observations+=1;self.first_observation=self.first_observation or iso;self.last_observation=iso
  if v is None:return
  self.numeric_count+=1;is_sentinel=v in sentinels;state='SENTINEL' if is_sentinel else 'VALID'
  if is_sentinel:self.sentinel_count+=1
  else:
   self.valid_count+=1;self.total+=v;self.minimum=v if self.minimum is None else min(self.minimum,v);self.maximum=v if self.maximum is None else max(self.maximum,v);self.first_valid=self.first_valid or iso;self.last_valid=iso
  if self.previous_state and self.previous_state!=state:
   self.state_transition_count+=1
   item={'at':iso,'from':self.previous_state,'to':state,'value':v}
   if len(self.transitions)<max_transitions:self.transitions.append(item)
   else:self.transition_overflow+=1
  self.previous_state=state
 def report(self):
  d=asdict(self);d.pop('total');d.pop('previous_state');d['mean']=round(self.total/self.valid_count,4) if self.valid_count else None;d['valid_pct_of_numeric']=round(100*self.valid_count/self.numeric_count,4) if self.numeric_count else 0;return d

def find_files(root):
 found=[]
 for p in root.rglob('*'):
  if not p.is_file():continue
  for suffix,stype in SUFFIXES.items():
   if p.name.lower().endswith(suffix):found.append((p,stype));break
 return sorted(found,key=lambda x:str(x[0]))
def save(path,root,stats,done,schemas,counters,args,complete=False):
 payload={'version':VERSION,'complete':complete,'root':str(root),'updated_at':datetime.now().isoformat(timespec='seconds'),'configuration':{'sentinels':sorted(args.sentinels),'max_transitions_per_channel':args.max_transitions},'progress':dict(counters),'completed_files':sorted(done),'schemas':schemas,'sensor_channel_analysis':{k:v.report() for k,v in sorted(stats.items())},'note':'Streaming descriptive analysis only. Physical sensor identity is not inferred; 100 is not globally treated as sentinel.'}
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n');tmp.replace(path)
def restore(path):
 stats={};done=set();schemas={};counters={}
 if not path.exists():return stats,done,schemas,counters
 j=json.loads(path.read_text());done=set(j.get('completed_files',[]));schemas=j.get('schemas',{});counters=j.get('progress',{})
 for k,d in j.get('sensor_channel_analysis',{}).items():
  s=Stat();
  for n in ('observations','numeric_count','valid_count','sentinel_count','minimum','maximum','first_observation','last_observation','first_valid','last_valid','state_transition_count','transitions','transition_overflow'):
   if n in d:setattr(s,n,d[n])
  s.total=(d.get('mean') or 0)*s.valid_count;s.previous_state=None;stats[k]=s
 return stats,done,schemas,counters
def process_file(path,stype,stats,schemas,counters,args):
 with path.open(encoding='utf-8-sig',errors='replace') as f:
  first=''
  for first in f:
   if first.strip():break
  if not first.strip():schemas[str(path)]={'source_type':stype,'empty':True};counters['empty_files']=counters.get('empty_files',0)+1;return
  d=delim(first);headers=[safe(x) for x in split(first.strip(),d)];rows=bad=0
  for line in f:
   if not line.strip():continue
   a=split(line.strip(),d);dt=parse_dt(a)
   if dt is None:bad+=1;continue
   rows+=1
   for i,x in enumerate(a[5:],5):
    name=headers[i] if i<len(headers) else f'column_{i+1}';key=f'{stype}.{name}';stats.setdefault(key,Stat()).add(dt,number(x),args.sentinels,args.max_transitions)
  schemas[str(path)]={'source_type':stype,'delimiter':d or 'whitespace','headers':headers,'columns':len(headers),'rows_parsed':rows,'unparsed_rows':bad};counters['rows_parsed']=counters.get('rows_parsed',0)+rows;counters['unparsed_rows']=counters.get('unparsed_rows',0)+bad

def main():
 ap=argparse.ArgumentParser(description='Pi-safe streaming Weather Display sensor analysis')
 ap.add_argument('raw_data',type=Path);ap.add_argument('--output',type=Path,default=Path('sensor_channel_analysis_streaming.json'));ap.add_argument('--checkpoint',type=Path,default=Path('sensor_channel_analysis.checkpoint.json'));ap.add_argument('--resume',action='store_true');ap.add_argument('--checkpoint-every',type=int,default=1,help='Save after N files');ap.add_argument('--max-transitions',type=int,default=500);ap.add_argument('--sentinels',type=float,nargs='*',default=sorted(DEFAULT_SENTINELS));ap.add_argument('--progress-every',type=int,default=1);ap.add_argument('--version',action='version',version=VERSION);args=ap.parse_args();args.sentinels=set(args.sentinels)
 if not args.raw_data.is_dir():ap.error('raw_data must be an existing directory')
 stats,done,schemas,counters=restore(args.checkpoint) if args.resume else ({},set(),{},{});files=find_files(args.raw_data);counters['files_discovered']=len(files);start=time.time();processed=0
 try:
  for idx,(path,stype) in enumerate(files,1):
   sp=str(path)
   if sp in done:continue
   process_file(path,stype,stats,schemas,counters,args);done.add(sp);processed+=1;counters['files_completed']=len(done);counters['channels']=len(stats)
   if processed%args.progress_every==0:print(f'[{len(done)}/{len(files)}] {path} | channels={len(stats)} rows={counters.get("rows_parsed",0):,}',flush=True)
   if processed%args.checkpoint_every==0:save(args.checkpoint,args.raw_data,stats,done,schemas,counters,args,False)
 except (KeyboardInterrupt,Exception) as e:
  save(args.checkpoint,args.raw_data,stats,done,schemas,counters,args,False);print(f'Checkpoint saved: {args.checkpoint}',file=sys.stderr)
  if isinstance(e,KeyboardInterrupt):return 130
  raise
 counters['elapsed_seconds']=round(time.time()-start,2);save(args.output,args.raw_data,stats,done,schemas,counters,args,True);save(args.checkpoint,args.raw_data,stats,done,schemas,counters,args,True);print(f'Complete: {len(stats)} channels, {counters.get("rows_parsed",0):,} rows. Output: {args.output}')
 return 0
if __name__=='__main__':raise SystemExit(main())
