#!/usr/bin/env python3
import argparse,sqlite3
from pathlib import Path
VERSION='1.0.0'
def connect(path):
 c=sqlite3.connect(path,timeout=30);c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=NORMAL');c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=5000');return c
def main():
 p=argparse.ArgumentParser();p.add_argument('database',type=Path);p.add_argument('--schema',type=Path,default=Path(__file__).with_name('weather_schema.sql'));a=p.parse_args();a.database.parent.mkdir(parents=True,exist_ok=True)
 c=connect(a.database);c.executescript(a.schema.read_text());c.execute("INSERT OR REPLACE INTO repository_meta VALUES('created_by',?)",(f'weather_db.py {VERSION}',));c.commit();print('quick_check:',c.execute('PRAGMA quick_check').fetchone()[0]);print('database:',a.database);c.close()
if __name__=='__main__':main()
