#!/bin/bash
set -euo pipefail
SRC=$(cd "$(dirname "$0")" && pwd)
BASE=/mnt/weathercam/app
DEST=$BASE/releases/HarpendenWeatherCamera-V50.3.4
REC=/etc/weathercam/v50_3_4-rollback-target
python3 "$SRC/verify_v50_3_4.py"
sudo mkdir -p "$BASE/releases" /etc/weathercam
if [ -L "$BASE/current" ]; then
  PREVIOUS=$(readlink -f "$BASE/current")
elif [ -d "$BASE/current" ]; then
  PREVIOUS="$BASE/current-pre-v50.3.4-$(date +%Y%m%d-%H%M%S)"
  sudo systemctl stop weathercam-dashboard.timer 2>/dev/null || true
  sudo systemctl stop weathercam.service 2>/dev/null || true
  sudo mv "$BASE/current" "$PREVIOUS"
else
  PREVIOUS=""
fi
[ -n "$PREVIOUS" ] && printf '%s\n' "$PREVIOUS" | sudo tee "$REC" >/dev/null
sudo systemctl stop weathercam-dashboard.timer 2>/dev/null || true
sudo systemctl stop weathercam.service 2>/dev/null || true
sudo rm -rf "$DEST"
sudo cp -a "$SRC" "$DEST"
python3 "$DEST/verify_v50_3_4.py"
sudo install -m 0644 "$DEST/systemd/weathercam-dashboard.service" /etc/systemd/system/weathercam-dashboard.service
sudo install -m 0644 "$DEST/systemd/weathercam-dashboard.timer" /etc/systemd/system/weathercam-dashboard.timer
[ -f /etc/weathercam/dashboard.env ] || sudo install -m 0600 "$DEST/dashboard.env.example" /etc/weathercam/dashboard.env
sudo rm -f "$BASE/current"
sudo ln -s "$DEST" "$BASE/current"
sudo systemctl daemon-reload
sudo systemctl start weathercam.service
sleep 8
if ! systemctl is-active --quiet weathercam.service; then
  echo "Camera failed to start. Run sudo bash /mnt/weathercam/app/current/rollback_v50_3_4.sh"
  exit 1
fi
sudo -u mgs /usr/bin/python3 "$BASE/current/weathercam_dashboard/dashboard.py"
sudo systemctl enable --now weathercam-dashboard.timer
echo "Installed V50.3.4 -> $(readlink -f "$BASE/current")"
