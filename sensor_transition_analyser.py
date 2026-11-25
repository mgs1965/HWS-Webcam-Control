#!/usr/bin/env python3
"""Targeted Weather Display sensor transition analyser v1.4.0.
Read-only and bounded-memory. Analyses only selected date windows.
"""
from __future__ import annotations
import argparse,csv,json,re,statistics,sys
from collections import defaultdict
from datetime import date,datetime,timedelta
from pathlib import Path
VERSION='1.4.0'
DEFAULT_WINDOWS={
 'ground_sensor_2012':('2012-02-01','2012-03-31','Extra Temperature Sensor 1 installed 2012-02-14'),
 'soil_install_2015':('2015-03-01','2015-04-15','Soil temperature and moisture installed 2015-03-15'),
 'greenhouse_2018':('2017-12-15','2018-01-31','Greenhouse Temperature 2 added 2018-01-02'),
 'controller_repair_2022':('2022-03-01','2022-04-15','Controller repair/channel change 2022-03-24'),
}
SOURCE_SUFFIXES={'vantageextrasensorslog.csv':'vantage_extra_sensors','extralog.csv':'extra_log'}
INVALID_COMMON={-1000.0,-100.0,1000.0,2550.0}
def safe(s):return re.sub(r'[^a-z0-9]+','_',str(s).strip().lower()).strip('_')
def num(s):
 try:return float(str(s).strip())
 except:return None
def invalid(channel,v):
 if v is None:return True
 if v in INVALID_COMMON:return True
 # Weather Display/Davis inactive values found in this archive.
 if v==-148.0:return True
 if channel.startswith('vantage_extra_sensors.') and v==255.0:return True
 # Fixed zero humidity channels are retained as numeric but labelled suspicious later.
 return False
def parse_dt(a):
 try:return datetime(int(float(a[2])),int(float(a[1])),int(float(a[0])),int(float(a[3])),int(float(a[4])))
 except:return None
def delimiter(line):
 if line.count(',')>=2:return ','
 if line.count(';')>=2:return ';'
 if line.count('\t')>=2:return '\t'
 return None
def split(line,d):
 if d:return next(csv.reader([line],delimiter=d))
 return line.split()
def percentile(values,p):
 if not values:return None
 a=sorted(values);i=(len(a)-1)*p;lo=int(i);hi=min(lo+1,len(a)-1);return a[lo]+(a[hi]-a[lo])*(i-lo)
class Acc:
 def __init__(self,max_samples):
  self.n=0;self.invalid=0;self.sum=0.0;self.min=None;self.max=None;self.values=[];self.max_samples=max_samples;self.first=None;self.last=None;self.zeros=0
 def add(self,dt,v,is_invalid):
  self.n+=1;self.first=self.first or dt.isoformat();self.last=dt.isoformat()
  if is_invalid:self.invalid+=1;return
  self.sum+=v;self.min=v if self.min is None else min(self.min,v);self.max=v if self.max is None else max(self.max,v);self.zeros+=v==0
  # Deterministic bounded reservoir: retain evenly thinned observed values.
  if len(self.values)<self.max_samples:self.values.append(v)
  else:
   idx=(self.n*2654435761)%self.n
   if idx<self.max_samples:self.values[idx]=v
 def report(self):
  valid=self.n-self.invalid
  return {'observations':self.n,'valid_count':valid,'invalid_count':self.invalid,'valid_pct':round(100*valid/self.n,3) if self.n else 0,'first':self.first,'last':self.last,'minimum':self.min,'maximum':self.max,'mean':round(self.sum/valid,4) if valid else None,'median_sample':round(statistics.median(self.values),4) if self.values else None,'p05_sample':round(percentile(self.values,.05),4) if self.values else None,'p95_sample':round(percentile(self.values,.95),4) if self.values else None,'zero_pct_of_valid':round(100*self.zeros/valid,3) if valid else 0,'sample_size':len(self.values),'suspicious_constant_zero':bool(valid and self.zeros==valid)}
def find_files(root,start,end):
 out=[]
 for p in root.rglob('*'):
  if not p.is_file():continue
  st=None
  for suffix,t in SOURCE_SUFFIXES.items():
   if p.name.lower().endswith(suffix):st=t;break
  if not st:continue
  # Directory years/months provide a cheap filter; content still controls inclusion.
  out.append((p,st))
 return sorted(out,key=lambda x:str(x[0]))
def analyse_window(root,name,start,end,note,max_samples,sample_rows):
 acc=defaultdict(lambda:Acc(max_samples));daily=defaultdict(lambda:defaultdict(lambda:Acc(min(max_samples,500))));examples=[];files=[];rows=bad=0
 for path,stype in find_files(root,start,end):
  try:
   with path.open(encoding='utf-8-sig',errors='replace') as f:
    first=''
    for first in f:
     if first.strip():break
    if not first.strip():continue
    d=delimiter(first);headers=[safe(x) for x in split(first.strip(),d)]
    used=False
    for line in f:
     if not line.strip():continue
     a=split(line.strip(),d);dt=parse_dt(a)
     if dt is None:bad+=1;continue
     if not (start<=dt.date()<=end):continue
     used=True;rows+=1;example={'timestamp':dt.isoformat(),'source_type':stype}
     for i,x in enumerate(a[5:],5):
      col=headers[i] if i<len(headers) else f'column_{i+1}';key=f'{stype}.{col}';v=num(x);inv=invalid(key,v);acc[key].add(dt,v,inv);daily[dt.date().isoformat()][key].add(dt,v,inv)
      if not inv:example[col]=v
     if len(examples)<sample_rows:examples.append(example)
    if used:files.append(str(path))
  except OSError as e:bad+=1
 return {'name':name,'start':start.isoformat(),'end':end.isoformat(),'documentary_note':note,'files':files,'rows_parsed':rows,'unparsed_rows':bad,'channels':{k:v.report() for k,v in sorted(acc.items())},'daily':{day:{k:v.report() for k,v in sorted(ch.items())} for day,ch in sorted(daily.items())},'sample_rows':examples}
def parse_window(s):
 try:name,start,end,note=s.split(':',3);return name,date.fromisoformat(start),date.fromisoformat(end),note
 except Exception:raise argparse.ArgumentTypeError('Use NAME:YYYY-MM-DD:YYYY-MM-DD:NOTE')
def main():
 ap=argparse.ArgumentParser(description='Low-memory targeted sensor transition analyser')
 ap.add_argument('raw_data',type=Path);ap.add_argument('--output',type=Path,default=Path('sensor_transition_analysis.json'));ap.add_argument('--window',action='append',type=parse_window,help='Custom NAME:START:END:NOTE; repeatable. Replaces defaults.')
 ap.add_argument('--max-samples',type=int,default=2000);ap.add_argument('--sample-rows',type=int,default=25);ap.add_argument('--version',action='version',version=VERSION);args=ap.parse_args()
 if not args.raw_data.is_dir():ap.error('raw_data must be an existing directory')
 if args.max_samples<10 or args.max_samples>20000:ap.error('--max-samples must be 10..20000')
 windows=args.window or [(n,date.fromisoformat(s),date.fromisoformat(e),note) for n,(s,e,note) in DEFAULT_WINDOWS.items()]
 result={'version':VERSION,'root':str(args.raw_data),'generated_at':datetime.now().isoformat(timespec='seconds'),'sentinel_policy':{'common':sorted(INVALID_COMMON),'extra_temperature':[-148.0],'vantage_inactive':[255.0],'note':'Zero is retained but flagged when a channel is constant zero.'},'windows':[]}
 for i,(name,start,end,note) in enumerate(windows,1):
  print(f'[{i}/{len(windows)}] {name}: {start} through {end}',flush=True);w=analyse_window(args.raw_data,name,start,end,note,args.max_samples,args.sample_rows);result['windows'].append(w);print(f'  files={len(w["files"])} rows={w["rows_parsed"]:,} channels={len(w["channels"])}',flush=True)
 tmp=args.output.with_suffix(args.output.suffix+'.tmp');tmp.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');tmp.replace(args.output);print(f'Complete: {args.output}')
 return 0
if __name__=='__main__':raise SystemExit(main())
