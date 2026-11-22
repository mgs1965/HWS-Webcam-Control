#!/bin/bash
set -euo pipefail
BASE=/mnt/weathercam/app
REC=/etc/weathercam/v54_5-rollback-target
[ -s "$REC" ] || { echo "Rollback target missing: $REC"; exit 1; }
TARGET=$(cat "$REC")
[ -e "$TARGET" ] || { echo "Rollback release missing: $TARGET"; exit 1; }
sudo systemctl stop weathercam-dashboard.timer 2>/dev/null || true
sudo systemctl stop weathercam.service
sudo rm -f "$BASE/current"
sudo ln -s "$TARGET" "$BASE/current"
sudo systemctl daemon-reload
sudo systemctl start weathercam.service
systemctl is-active --quiet weathercam.service || { echo 'Rollback target camera failed to start'; exit 1; }
sudo systemctl enable --now weathercam-dashboard.timer 2>/dev/null || true
echo "Rolled back -> $TARGET"
