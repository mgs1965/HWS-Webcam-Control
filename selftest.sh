#!/bin/bash
# Check an installed Pi end to end and print PASS/WARN/FAIL per item. Safe to run any time:
#   cd /mnt/weathercam/app/current && bash selftest.sh        (add --notify to also send a test alert)
BASE=/mnt/weathercam/app
ROOT=/mnt/weathercam
FAILS=0
pass() { echo "PASS  $1"; }
warn() { echo "WARN  $1"; }
fail() { echo "FAIL  $1"; FAILS=$((FAILS + 1)); }
HERE=$(cd "$(dirname "$0")" && pwd)
VER=$(grep -m1 '^VERSION=' "$HERE/version.py" | cut -d'"' -f2)
echo "Harpenden Weather Station self-test, version $VER"
[ "$(readlink -f "$BASE/current")" = "$HERE" ] && pass "current release is $VER" || warn "this folder is not the active release ($(readlink -f "$BASE/current"))"
systemctl is-active --quiet weathercam.service && pass "camera service running" || fail "camera service not running"
AGE=$(( $(date +%s) - $(stat -c %Y "$ROOT/frames/latest.jpg" 2>/dev/null || echo 0) ))
[ "$AGE" -lt 600 ] && pass "camera image is ${AGE}s old" || fail "camera image is ${AGE}s old (or missing)"
if [ -f "$ROOT/logs/weather_station.json" ]; then
  WAGE=$(( $(date +%s) - $(stat -c %Y "$ROOT/logs/weather_station.json") ))
  [ "$WAGE" -lt 1800 ] && pass "weather data is ${WAGE}s old" || fail "weather data is ${WAGE}s old"
else warn "no weather_station.json (Meteobridge not configured?)"; fi
for t in weathercam-dashboard weathercam-alerts weathercam-update weathercam-backup; do
  systemctl is-enabled --quiet $t.timer 2>/dev/null && pass "$t.timer enabled" || warn "$t.timer not enabled (optional; see dashboard.env.example)"
done
python3 "$HERE/verify.py" >/dev/null 2>&1 && pass "release files verify" || fail "verify.py reports a problem"
OUT=${DASHBOARD_OUT:-$ROOT/dashboard}
[ -s "$OUT/index.html" ] && pass "dashboard site generated ($OUT)" || fail "no generated site at $OUT"
[ -s "$ROOT/logs/dashboard_news.json" ] && pass "news file present" || warn "no news file yet (run install.sh or dashboard.py --import-news-archive)"
python3 -c "
import sys;sys.path.insert(0,'$HERE')
import alerts
p=alerts.find_problems()
[print('FAIL  alert check: '+m) for m in p.values()]
print('PASS  health checks clean' if not p else '')
sys.exit(1 if p else 0)" || FAILS=$((FAILS + 1))
if [ -f /etc/weathercam/dashboard.env ] && sudo grep -q '^GITHUB_TOKEN=.' /etc/weathercam/dashboard.env; then
  bash "$HERE/update.sh" --check >/tmp/hws-selftest-update.txt 2>&1 && pass "update check: $(tail -1 /tmp/hws-selftest-update.txt)" || fail "update check failed: $(tail -1 /tmp/hws-selftest-update.txt)"
else warn "GITHUB_TOKEN not set; update check skipped"; fi
[ -e "$ROOT/logs/update_failed" ] && fail "last automatic update failed: $(cat "$ROOT/logs/update_failed")"
[ -e "$ROOT/logs/backup_failed" ] && fail "last backup failed: $(cat "$ROOT/logs/backup_failed")"
if [ "${1:-}" = "--notify" ]; then python3 "$HERE/alerts.py" --test && pass "test alert sent (or printed if no destination is set)"; fi
echo; [ $FAILS -eq 0 ] && echo "All checks passed." || echo "$FAILS check(s) failed."
exit $((FAILS > 0))
