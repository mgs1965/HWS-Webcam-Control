#!/usr/bin/env python3
"""Weekly summary of the last 7 complete days (rain, extremes, data coverage, open problems).

  python3 digest.py --print    show it
  python3 digest.py            send it through the same channels as the health alerts
Enabled by HWS_DIGEST=1 (weathercam-digest.timer, Mondays 08:00).
"""
import json
import sys
from datetime import date, timedelta

import alerts


def load_days(history=None, daily_log=None):
    """Merge the history 'daily' list with the live daily log; the history wins for finished days."""
    days = {}
    try:
        raw = json.loads((daily_log or alerts.LOGS / 'weather_station_daily_log.json').read_text(encoding='utf-8')).get('days')
        if isinstance(raw, dict):
            days.update({k: v for k, v in raw.items() if isinstance(v, dict)})
    except (OSError, ValueError):
        pass
    try:
        rows = json.loads((history or alerts.LOGS / 'weather_station_history.json').read_text(encoding='utf-8')).get('daily')
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get('date'):
                days[str(row['date'])[:10]] = row
    except (OSError, ValueError):
        pass
    return days


def build(days, today, problems=None):
    wanted = [(today - timedelta(days=n)).isoformat() for n in range(7, 0, -1)]
    rows = [(d, days[d]) for d in wanted if d in days]
    first, last = wanted[0], wanted[-1]
    lines = ['Harpenden Weather Station: week %s to %s' % (first, last)]
    if not rows:
        lines.append('No weather data was recorded this week.')
    else:
        def best(key, pick):
            vals = [(r[key], d) for d, r in rows if isinstance(r.get(key), (int, float))]
            return pick(vals) if vals else None
        rain = [(r['rain_mm'], d) for d, r in rows if isinstance(r.get('rain_mm'), (int, float))]
        if rain:
            wet = max(rain)
            lines.append('Rain: %.1f mm in total (wettest day %s, %.1f mm; %d dry days)' % (sum(v for v, _ in rain), wet[1], wet[0], sum(1 for v, _ in rain if v < 0.2)))
        hot, cold, gust = best('temp_max_c', max), best('temp_min_c', min), best('wind_gust_mph', max)
        if hot:
            lines.append('Warmest: %.1f C on %s' % hot)
        if cold:
            lines.append('Coldest: %.1f C on %s' % cold)
        if gust:
            lines.append('Strongest gust: %.0f mph on %s' % gust)
        lines.append('Data recorded on %d of 7 days' % len(rows))
    found = alerts.find_problems() if problems is None else problems
    lines.append('Open problems: %s' % ('; '.join(found.values()) if found else 'none'))
    return '\n'.join(lines)


def main(argv):
    text = build(load_days(), date.today())
    if '--print' in argv:
        print(text)
        return 0
    return 0 if alerts.send(text) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
