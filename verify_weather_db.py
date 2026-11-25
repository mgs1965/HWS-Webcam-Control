#!/usr/bin/env python3
import argparse,sqlite3
from pathlib import Path
from weather_db import connect
def main():
 p=argparse.ArgumentParser();p.add_argument('database',type=Path);a=p.parse_args();c=connect(a.database)
 print('quick_check:',c.execute('pragma quick_check').fetchone()[0]);print('observations:',c.execute('select count(*) from observation').fetchone()[0]);print('range:',c.execute("select min(timestamp_local),max(timestamp_local) from observation").fetchone());print('sources:',c.execute('select s.code,count(*) from observation o join source_system s on s.id=o.source_system_id group by s.code').fetchall());print('ground rows:',c.execute('select count(*) from observation where ground_temperature_c is not null').fetchone()[0]);print('rain total:',c.execute('select round(sum(rain_interval_mm),1) from observation').fetchone()[0]);print('batches:',c.execute('select id,status,rows_read,rows_inserted,rows_rejected from import_batch').fetchall());c.close()
if __name__=='__main__':main()
