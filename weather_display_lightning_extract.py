#!/usr/bin/env python3
"""Weather Display lightning log extractor v1.3.1.
Scans Raw Data recursively for *lightninglog.txt and emits a separate normalised
lightning-event CSV plus JSON audit report. Standard library only.
"""
from __future__ import annotations
import argparse,csv,json,re
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
VERSION='1.3.1'; DEFAULT_CUTOFF='2023-01-01T00:00:00'
BASE=['observed_at_local','observed_at_utc','source_system','source_file','source_line','event_sequence','raw_fields_json','quality_flags']
def safe(x):return re.sub(r'[^a-z0-9]+','_',str(x).strip().lower()).strip('_') or 'unnamed'
def num(x):
 try:return float(x)
 except:return None
def delimiter(line):
 if line.count(',')>=2:return ','
 if line.count(';')>=2:return ';'
 if line.count('\t')>=2:return '\t'
 return None
def split(line,d):
 if d==',':return next(csv.reader([line]))
 if d==';':return next(csv.reader([line],delimiter=';'))
 if d=='\t':return line.split('\t')
 return line.split()
def parse_dt(fields,headers):
 h=[safe(x) for x in headers]
 def ix(*names):
  for x in names:
   if x in h:return h.index(x)
  return None
 # WD five-column form
 try:return datetime(int(float(fields[2])),int(float(fields[1])),int(float(fields[0])),int(float(fields[3])),int(float(fields[4]))),{0,1,2,3,4}
 except:pass
 di,mi,yi=ix('day','dd'),ix('month','mm'),ix('year','yyyy'); hi,ni=ix('hour','hh'),ix('minute','min')
 if None not in (di,mi,yi,hi,ni):
  try:return datetime(int(float(fields[yi])),int(float(fields[mi])),int(float(fields[di])),int(float(fields[hi])),int(float(fields[ni]))),{di,mi,yi,hi,ni}
  except:pass
 date_i=ix('date','record_date'); time_i=ix('time','record_time')
 if date_i is not None:
  ds=fields[date_i]; ts=fields[time_i] if time_i is not None else '00:00'
  for fmt in ('%d/%m/%Y %H:%M','%d-%m-%Y %H:%M','%Y-%m-%d %H:%M','%m/%d/%Y %H:%M','%d/%m/%Y %H:%M:%S'):
   try:return datetime.strptime(ds+' '+ts,fmt),{date_i}|({time_i} if time_i is not None else set())
   except ValueError:pass
 for used,val in (({0},fields[0] if fields else ''),({0,1},' '.join(fields[:2]) if len(fields)>1 else '')):
  for fmt in ('%d/%m/%Y %H:%M','%Y-%m-%d %H:%M','%d/%m/%Y %H:%M:%S','%Y-%m-%dT%H:%M:%S'):
   try:return datetime.strptime(val,fmt),used
   except ValueError:pass
 return None,set()
def looks_header(fields):
 if len(fields)<2:return False
 return sum(any(c.isalpha() for c in x) for x in fields)>=2
def analyse_file(path):
 lines=[x for x in path.read_text(encoding='utf-8-sig',errors='replace').splitlines() if x.strip()]
 if not lines:return [],{'empty':True}
 d=delimiter(lines[0]); first=split(lines[0],d); has_header=looks_header(first)
 headers=[safe(x) for x in first] if has_header else [f'column_{i+1}' for i in range(len(first))]
 data=lines[1:] if has_header else lines
 rows=[];bad=0
 for lineno,line in enumerate(data,2 if has_header else 1):
  f=split(line,d); dt,used=parse_dt(f,headers)
  if dt is None:bad+=1;continue
  raw={}
  for i,x in enumerate(f):
   if i in used:continue
   k=headers[i] if i<len(headers) else f'column_{i+1}'; v=num(x);raw[k]=v if v is not None else x.strip()
  rows.append((dt,lineno,raw))
 return rows,{'empty':False,'delimiter':d or 'whitespace','headers':headers,'columns':len(headers),'rows_parsed':len(rows),'unparsed_rows':bad}
def main():
 ap=argparse.ArgumentParser(description='Extract Weather Display lightning logs to event CSV')
 ap.add_argument('raw_data',type=Path);ap.add_argument('--output',type=Path,default=Path('weather_display_lightning_events.csv'));ap.add_argument('--report',type=Path,default=Path('weather_display_lightning_report.json'));ap.add_argument('--timezone',default='Europe/London');ap.add_argument('--cutoff',default=DEFAULT_CUTOFF);ap.add_argument('--from-date');ap.add_argument('--to-date');ap.add_argument('--version',action='version',version=VERSION);a=ap.parse_args()
 tz=ZoneInfo(a.timezone);cutoff=datetime.fromisoformat(a.cutoff);start=datetime.fromisoformat(a.from_date) if a.from_date else None;end=datetime.fromisoformat(a.to_date+'T23:59:59') if a.to_date else None
 files=sorted(p for p in a.raw_data.rglob('*') if p.is_file() and p.name.lower().endswith('lightninglog.txt'))
 schemas={};events=[];stats=Counter()
 for p in files:
  rows,meta=analyse_file(p);schemas[str(p)]=meta;stats['files_parsed']+=1;stats['unparsed_rows']+=meta.get('unparsed_rows',0)
  for dt,line,raw in rows:
   if dt>=cutoff or (start and dt<start) or (end and dt>end):continue
   events.append((dt,str(p),line,raw))
 events.sort(key=lambda x:(x[0],x[1],x[2])); dup=Counter((x[0],json.dumps(x[3],sort_keys=True)) for x in events);seq=Counter()
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with a.output.open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=BASE);w.writeheader()
  for dt,p,line,raw in events:
   seq[dt]+=1;flags=[]
   if dup[(dt,json.dumps(raw,sort_keys=True))]>1:flags.append('EXACT_DUPLICATE_EVENT')
   aware=dt.replace(tzinfo=tz)
   w.writerow({'observed_at_local':dt.isoformat(timespec='minutes'),'observed_at_utc':aware.astimezone(timezone.utc).isoformat(timespec='minutes'),'source_system':'WEATHER_DISPLAY','source_file':p,'source_line':line,'event_sequence':seq[dt],'raw_fields_json':json.dumps(raw,separators=(',',':'),sort_keys=True),'quality_flags':';'.join(flags)})
 report={'version':VERSION,'root':str(a.raw_data),'cutoff':a.cutoff,'files_discovered':len(files),'events_written':len(events),'first_event':events[0][0].isoformat() if events else None,'last_event':events[-1][0].isoformat() if events else None,'unparsed_rows':stats['unparsed_rows'],'exact_duplicate_event_rows':sum(v-1 for v in dup.values() if v>1),'schemas':schemas,'note':'Lightning fields are preserved from source headers/raw columns. No undocumented semantics are inferred.'}
 a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(f'Wrote {len(events):,} lightning events to {a.output}');print(f'Report: {a.report}')
if __name__=='__main__':main()
