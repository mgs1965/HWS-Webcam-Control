#!/usr/bin/env python3
"""Weather Display normalised extractor v1.1.0.

Streams Raw Data/<year>/<month> month by month, combines Weather Display logs,
deduplicates timestamps, applies optional dated sensor mappings, and writes a
normalised CSV plus an audit report. Standard library only, Python 3.9+.
"""
from __future__ import annotations
import argparse,csv,json,re
from collections import Counter,defaultdict
from dataclasses import dataclass
from datetime import date,datetime,timezone
from pathlib import Path
from typing import Dict,Iterable,List,Optional,Tuple
from zoneinfo import ZoneInfo

VERSION="1.2.0"; DEFAULT_CUTOFF="2023-01-01T00:00:00"
BASE_FIELDS=["temperature_c","humidity_pct","dew_point_c","pressure_hpa","wind_speed_mph","wind_gust_mph","wind_direction_deg","rain_last_minute_mm","daily_rain_counter_mm","monthly_rain_counter_mm","yearly_rain_counter_mm","heat_index_c"]
VANTAGE_FIELDS=["solar_radiation_wm2","uv_index","daily_et_mm","vantage_extra_1_raw","vantage_extra_2_raw"]
OUTPUT_FIELDS=["observed_at_local","observed_at_utc","source_system","source_resolution_minutes",*BASE_FIELDS,*VANTAGE_FIELDS,"indoor_temperature_c","indoor_humidity_pct","extra_measurements_json","source_files","quality_flags"]
KNOWN_SUFFIXES=[("vantagelogten.txt","vantage10"),("vantagelog.txt","vantage"),("indoorlog.txt","indoor"),("lgcsv60.csv","csv60"),("lgten.txt","base10"),("lgsun.txt","daily_sun"),("lg2.txt","daily_extremes"),("vantageextrasensorslog.csv","vantage_extra_sensors"),("growlogten.txt","grow10"),("extralog.csv","extra_log"),("currentcostlog.txt","current_cost"),("lg.txt","base")]
@dataclass
class SourceRow: values:Dict[str,object]; file:str; line:int; resolution:int; source_type:str

def num(s):
 try:return float(s)
 except:return None

def parse_dt(p):
 try:return datetime(int(p[2]),int(p[1]),int(p[0]),int(p[3]),int(p[4]))
 except:return None

def kind(name):
 n=name.lower()
 for suffix,k in KNOWN_SUFFIXES:
  if n.endswith(suffix):return k
 return None

def month_from_path(p:Path,root:Path):
 try: rel=p.relative_to(root); parts=rel.parts
 except ValueError:return None
 for i in range(len(parts)-1):
  if re.fullmatch(r"\d{4}",parts[i]) and re.fullmatch(r"(?:0?[1-9]|1[0-2])",parts[i+1]):
   return int(parts[i]),int(parts[i+1])
 return None

def discover(root:Path):
 months=defaultdict(lambda:defaultdict(list)); unknown=[]; all_files=0
 for p in root.rglob("*"):
  if not p.is_file():continue
  all_files+=1; ym=month_from_path(p,root); k=kind(p.name)
  if ym and k:months[ym][k].append(p)
  elif ym and not k:unknown.append(str(p))
 return months,unknown,all_files

def selected(ym,start,end,cutoff):
 y,m=ym; a=date(y,m,1)
 if start and date(y,m,28)<start.replace(day=1):return False
 if end and a>end.replace(day=1):return False
 return datetime(y,m,1)<cutoff

def iter_rows(path):
 with path.open("r",encoding="utf-8-sig",errors="replace") as f:
  for line_no,line in enumerate(f,1):
   p=line.strip().replace(","," ").split()
   if p:yield line_no,p

def parse_files(paths,fields,resolution,stype,counters):
 out=defaultdict(list)
 for path in sorted(paths):
  counters["files_parsed"][stype]+=1
  for line,p in iter_rows(path):
   dt=parse_dt(p)
   if dt is None:continue
   vals={k:(num(p[i]) if i<len(p) else None) for i,k in enumerate(fields,5)}
   if len(p)>5+len(fields):vals["unmapped_columns"]=[num(x) if num(x) is not None else x for x in p[5+len(fields):]]
   out[dt].append(SourceRow(vals,str(path),line,resolution,stype)); counters["rows_read"][stype]+=1
 return out


def safe_name(value):
 return re.sub(r"[^a-z0-9]+","_",str(value).strip().lower()).strip("_") or "unnamed"

def split_flexible(line, delimiter=None):
 line=line.strip().lstrip("\ufeff")
 if delimiter==",": return next(csv.reader([line]))
 if delimiter==";": return next(csv.reader([line],delimiter=";"))
 if delimiter=="\t": return line.split("\t")
 return line.split()

def identify_delimiter(line):
 if line.count(",")>=2:return ","
 if line.count(";")>=2:return ";"
 if line.count("\t")>=2:return "\t"
 return None

def parse_flexible_datetime(fields, header=None):
 # Standard Weather Display five-column date/time form.
 dt=parse_dt(fields)
 if dt is not None:return dt,5
 h=[safe_name(x) for x in (header or [])]
 def idx(*names):
  for n in names:
   if n in h:return h.index(n)
  return None
 # Separate named columns.
 di,mi,yi=idx("day","dd"),idx("month","mm"),idx("year","yyyy")
 hi,ni=idx("hour","hh"),idx("minute","min")
 if None not in (di,mi,yi,hi,ni):
  try:return datetime(int(float(fields[yi])),int(float(fields[mi])),int(float(fields[di])),int(float(fields[hi])),int(float(fields[ni]))),0
  except:pass
 # Date and optional time columns.
 date_i=idx("date","record_date"); time_i=idx("time","record_time")
 if date_i is not None:
  ds=fields[date_i].strip(); ts=fields[time_i].strip() if time_i is not None and time_i<len(fields) else "00:00"
  for fmt in ("%d/%m/%Y %H:%M","%d-%m-%Y %H:%M","%Y-%m-%d %H:%M","%m/%d/%Y %H:%M"):
   try:return datetime.strptime(ds+" "+ts,fmt),0
   except ValueError:pass
 # Combined first field or first two fields.
 candidates=[fields[0]] if fields else []
 if len(fields)>1:candidates.append(fields[0]+" "+fields[1])
 for value in candidates:
  for fmt in ("%d/%m/%Y %H:%M","%d-%m-%Y %H:%M","%Y-%m-%d %H:%M","%d/%m/%Y %H:%M:%S","%Y-%m-%dT%H:%M:%S"):
   try:return datetime.strptime(value,fmt),1 if value==fields[0] else 2
   except ValueError:pass
 return None,0

def parse_additional_files(paths,stype,resolution,counters,schema_inventory):
 """Header-driven parser for evolving extra sensor files.

 Values retain source-prefixed raw names. No physical sensor identity is inferred.
 """
 out=defaultdict(list)
 for path in sorted(paths):
  counters["files_parsed"][stype]+=1
  lines=path.read_text(encoding="utf-8-sig",errors="replace").splitlines()
  nonempty=[x for x in lines if x.strip()]
  if not nonempty:continue
  delimiter=identify_delimiter(nonempty[0]); first=split_flexible(nonempty[0],delimiter)
  # Header exists when first five fields are not a valid WD timestamp.
  header=first if parse_dt(first) is None else None
  data_lines=nonempty[1:] if header else nonempty
  generic_header=[f"column_{i+1}" for i in range(len(first))]
  names=[safe_name(x) for x in header] if header else generic_header
  schema_inventory[str(path)]={"source_type":stype,"delimiter":delimiter or "whitespace","headers":names,"columns":len(names)}
  for line_no,line in enumerate(data_lines,2 if header else 1):
   fields=split_flexible(line,delimiter)
   dt,consumed=parse_flexible_datetime(fields,header)
   if dt is None:
    counters["unparsed_rows"][stype]+=1;continue
   vals={}
   for i,x in enumerate(fields):
    n=names[i] if i<len(names) else f"column_{i+1}"
    if n in {"day","dd","month","mm","year","yyyy","hour","hh","minute","min","date","record_date","time","record_time"}:continue
    if not header and i<consumed:continue
    key=f"raw_{stype}_{n}"
    v=num(x);vals[key]=v if v is not None else x.strip()
   out[dt].append(SourceRow(vals,str(path),line_no,resolution,stype));counters["rows_read"][stype]+=1
 return out

def choose(rows,counters):
 flags=[]; stype=rows[0].source_type
 if len(rows)>1:
  sig=[json.dumps(r.values,sort_keys=True) for r in rows]
  if len(set(sig))==1:counters["duplicates"][stype]["exact"]+=len(rows)-1;flags.append("EXACT_DUPLICATE")
  else:counters["duplicates"][stype]["conflicting"]+=len(rows)-1;flags.append("CONFLICTING_DUPLICATE_LAST_USED")
 return rows[-1],flags

def load_mappings(path):
 if not path:return []
 data=json.loads(path.read_text(encoding="utf-8"))
 if not isinstance(data,list):raise ValueError("Mapping must be a JSON list")
 for x in data:
  for req in ("from","to","source_field","sensor_id"):
   if req not in x:raise ValueError(f"Mapping missing {req}: {x}")
 return data

def apply_mappings(dt,raw,mappings):
 answer={}; day=dt.date().isoformat()
 for m in mappings:
  if m["from"]<=day<=m["to"] and m["source_field"] in raw:
   v=raw[m["source_field"]]
   if v is not None and v not in m.get("sentinels",[-100,100,1000,-1000]):answer[m["sensor_id"]]={"value":v,"unit":m.get("unit"),"source_channel":m["source_field"],"confidence":m.get("confidence","CONFIRMED")}
 return answer

def quality(v):
 q=[]
 if v.get("humidity_pct") is not None and not 0<=v["humidity_pct"]<=100:q.append("SUSPECT_HUMIDITY")
 if v.get("wind_direction_deg") is not None and not 0<=v["wind_direction_deg"]<=360:q.append("SUSPECT_WIND_DIRECTION")
 if v.get("pressure_hpa") is not None and not 850<=v["pressure_hpa"]<=1100:q.append("SUSPECT_PRESSURE")
 if v.get("temperature_c") is not None and not -40<=v["temperature_c"]<=55:q.append("SUSPECT_TEMPERATURE")
 if v.get("wind_speed_mph") is not None and v.get("wind_gust_mph") is not None and v["wind_gust_mph"]<v["wind_speed_mph"]:q.append("INFO_WIND_EXCEEDS_REPORTED_GUST")
 if v.get("dew_point_c") is not None and v.get("temperature_c") is not None and v["dew_point_c"]>v["temperature_c"]+0.5:q.append("SUSPECT_DEWPOINT_ABOVE_TEMPERATURE")
 return q

def month_expected(y,m):
 import calendar
 return calendar.monthrange(y,m)[1]*1440

def write_example(path):
 data=[{"from":"YYYY-MM-DD","to":"YYYY-MM-DD","source_field":"confirmed_raw_field","sensor_id":"SOIL_TEMPERATURE","unit":"C","confidence":"CONFIRMED","sentinels":[-100,100,1000,-1000]}]
 path.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")

def main():
 ap=argparse.ArgumentParser(description="Weather Display Raw Data to normalised CSV, month-streaming v1.1")
 ap.add_argument("raw_data",nargs="?",type=Path);ap.add_argument("--output",type=Path,default=Path("weather_display_normalised.csv"));ap.add_argument("--report",type=Path,default=Path("weather_display_extract_report.json"));ap.add_argument("--mapping",type=Path);ap.add_argument("--cutoff",default=DEFAULT_CUTOFF);ap.add_argument("--timezone",default="Europe/London");ap.add_argument("--from-date");ap.add_argument("--to-date");ap.add_argument("--write-example-mapping",type=Path);ap.add_argument("--version",action="version",version=VERSION)
 a=ap.parse_args()
 if a.write_example_mapping:write_example(a.write_example_mapping);print(a.write_example_mapping);return 0
 if not a.raw_data or not a.raw_data.is_dir():ap.error("raw_data must be an existing directory")
 start=date.fromisoformat(a.from_date) if a.from_date else None;end=date.fromisoformat(a.to_date) if a.to_date else None;cutoff=datetime.fromisoformat(a.cutoff);tz=ZoneInfo(a.timezone);mappings=load_mappings(a.mapping)
 months,unknown,total_files=discover(a.raw_data); selected_months=[ym for ym in sorted(months) if selected(ym,start,end,cutoff)]
 counters={"rows_read":Counter(),"files_parsed":Counter(),"duplicates":defaultdict(lambda:Counter()),"unparsed_rows":Counter()};schema_inventory={};month_reports=[];output_first=output_last=None;rows_written=0
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with a.output.open("w",newline="",encoding="utf-8") as f:
  w=csv.DictWriter(f,fieldnames=OUTPUT_FIELDS);w.writeheader()
  for y,m in selected_months:
   g=months[(y,m)];base=parse_files(g.get("base",[]),BASE_FIELDS,1,"base",counters);base10=parse_files(g.get("base10",[]),BASE_FIELDS,10,"base10",counters);vant=parse_files(g.get("vantage",[]),VANTAGE_FIELDS,1,"vantage",counters);vant10=parse_files(g.get("vantage10",[]),VANTAGE_FIELDS,10,"vantage10",counters);ind=parse_files(g.get("indoor",[]),["indoor_temperature_c","indoor_humidity_pct"],1,"indoor",counters);ves=parse_additional_files(g.get("vantage_extra_sensors",[]),"vantage_extra_sensors",1,counters,schema_inventory);grow=parse_additional_files(g.get("grow10",[]),"grow10",10,counters,schema_inventory);xlog=parse_additional_files(g.get("extra_log",[]),"extra_log",1,counters,schema_inventory)
   times=sorted(set(base)|set(base10));prev=None;mr=Counter();mfirst=mlast=None
   for dt in times:
    if dt>=cutoff or (start and dt.date()<start) or (end and dt.date()>end):continue
    flags=[];sources=[]
    if dt in base:br,bf=choose(base[dt],counters);flags+=bf
    else:br,bf=choose(base10[dt],counters);flags+=["FALLBACK_10_MINUTE"]+bf;mr["fallback_10_minute"]+=1
    vals=dict(br.values);sources.append(f"{br.file}:{br.line}")
    vr=None
    if dt in vant:vr,vf=choose(vant[dt],counters);flags+=vf
    elif dt in vant10:vr,vf=choose(vant10[dt],counters);flags+=["VANTAGE_FALLBACK_10_MINUTE"]+vf
    if vr:vals.update(vr.values);sources.append(f"{vr.file}:{vr.line}")
    if dt in ind:ir,ix=choose(ind[dt],counters);flags+=ix;vals.update(ir.values);sources.append(f"{ir.file}:{ir.line}")
    if prev:
     gap=int((dt-prev).total_seconds()/60)-1
     if gap>0:flags.append(f"GAP_BEFORE_{gap}_MINUTES");mr["missing_minute_slots"]+=gap;mr["gap_events"]+=1
    prev=dt;flags+=quality(vals);extras={}
    if "unmapped_columns" in vals:extras["unmapped_columns"]=vals.pop("unmapped_columns")
    # Merge additional observations without assigning physical sensor identities.
    for dataset,label in ((ves,"vantage_extra_sensors"),(grow,"grow10"),(xlog,"extra_log")):
     if dt in dataset:
      xr,xf=choose(dataset[dt],counters);flags+=xf;sources.append(f"{xr.file}:{xr.line}")
      for key,value in xr.values.items():extras[key]={"value":value,"source_type":label,"source_channel":key.removeprefix("raw_"+label+"_")}
    mapped_input={k:(v.get("value") if isinstance(v,dict) else v) for k,v in extras.items()};mapped_input.update(vals)
    extras.update(apply_mappings(dt,mapped_input,mappings));aware=dt.replace(tzinfo=tz);row={k:"" for k in OUTPUT_FIELDS};row.update({"observed_at_local":dt.isoformat(timespec="minutes"),"observed_at_utc":aware.astimezone(timezone.utc).isoformat(timespec="minutes"),"source_system":"WEATHER_DISPLAY","source_resolution_minutes":br.resolution,"extra_measurements_json":json.dumps(extras,separators=(",",":"),sort_keys=True) if extras else "","source_files":";".join(sources),"quality_flags":";".join(sorted(set(flags)))})
    for k in BASE_FIELDS+VANTAGE_FIELDS+["indoor_temperature_c","indoor_humidity_pct"]:
     if vals.get(k) is not None:row[k]=vals[k]
    w.writerow(row);rows_written+=1;mr["rows_written"]+=1;mfirst=mfirst or dt;mlast=dt;output_first=output_first or dt;output_last=dt
   expected=month_expected(y,m); md=dict(mr); md.update({"year":y,"month":m,"expected_calendar_minutes":expected,"completeness_pct":round(mr["rows_written"]*100/expected,4),"first_output_timestamp":mfirst.isoformat() if mfirst else None,"last_output_timestamp":mlast.isoformat() if mlast else None,"files_found":{k:len(v) for k,v in sorted(g.items())}});month_reports.append(md)
 report={"version":VERSION,"root":str(a.raw_data),"cutoff":a.cutoff,"selection":{"from_date":a.from_date,"to_date":a.to_date},"archive_discovery":{"all_files":total_files,"month_directories_with_known_files":len(months),"first_month":f"{min(months)[0]:04d}-{min(months)[1]:02d}" if months else None,"last_month":f"{max(months)[0]:04d}-{max(months)[1]:02d}" if months else None,"unknown_files_count":len(unknown),"unknown_files":unknown},"output":{"selected_months":len(selected_months),"rows_written":rows_written,"first_timestamp":output_first.isoformat() if output_first else None,"last_timestamp":output_last.isoformat() if output_last else None},"files_parsed_by_type":dict(counters["files_parsed"]),"rows_read_by_type":dict(counters["rows_read"]),"duplicates_by_type":{k:dict(v) for k,v in counters["duplicates"].items()},"unparsed_rows_by_type":dict(counters["unparsed_rows"]),"additional_sensor_schemas":schema_inventory,"monthly_completeness":month_reports}
 a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8");print(f"Wrote {rows_written:,} observations to {a.output}");print(f"Report: {a.report}")
 return 0
if __name__=="__main__":raise SystemExit(main())
