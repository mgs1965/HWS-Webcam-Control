#!/usr/bin/env python3
"""Build Europe/London DST-aware daily summaries."""
import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/London")

def expected_minutes(day):
    start = datetime.combine(day, datetime.min.time(), tzinfo=TZ)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=TZ)
    return int((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() // 60)

def main():
    from weather_db import connect
    p = argparse.ArgumentParser()
    p.add_argument("database", type=Path)
    p.add_argument("--from-date")
    p.add_argument("--to-date")
    a = p.parse_args()
    c = connect(a.database)
    lo = a.from_date or c.execute("SELECT min(substr(timestamp_local,1,10)) FROM observation").fetchone()[0]
    hi = a.to_date or c.execute("SELECT max(substr(timestamp_local,1,10)) FROM observation").fetchone()[0]
    if not lo or not hi:
        raise SystemExit("No observations")
    cur, end_day = date.fromisoformat(lo), date.fromisoformat(hi)
    sql = '''INSERT OR REPLACE INTO daily_summary SELECT ?,min(temperature_c),max(temperature_c),avg(temperature_c),avg(humidity_percent),avg(dew_point_c),min(pressure_hpa),max(pressure_hpa),avg(pressure_hpa),sum(rain_interval_mm),max(wind_gust_mph),max(solar_radiation_wm2),max(uv_index),min(ground_temperature_c),max(ground_temperature_c),avg(ground_temperature_c),count(*),?,round(100.0*count(*)/?,3),max(quality_flags) FROM observation WHERE substr(timestamp_local,1,10)=?'''
    n = 0
    while cur <= end_day:
        day = cur.isoformat()
        expected = expected_minutes(cur)
        c.execute(sql, (day, expected, expected, day))
        n += 1
        if expected != 1440:
            print(f"DST day {day}: expected_minutes={expected}", flush=True)
        cur += timedelta(days=1)
    c.commit()
    print("summaries processed:", n)
    print("daily summaries total:", c.execute("select count(*) from daily_summary").fetchone()[0])
    c.close()

if __name__ == "__main__":
    main()
