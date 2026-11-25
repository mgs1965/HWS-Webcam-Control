#!/usr/bin/env python3
from datetime import date
from build_daily_summaries import expected_minutes

cases = {
    "2012-01-01": 1440,
    "2012-03-25": 1380,
    "2012-10-28": 1500,
    "2026-03-29": 1380,
    "2026-10-25": 1500,
}
for day, expected in cases.items():
    actual = expected_minutes(date.fromisoformat(day))
    assert actual == expected, (day, actual, expected)
    print(day, actual, "PASS")
