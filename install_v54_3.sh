#!/bin/bash
set -euo pipefail
SRC=$(cd "$(dirname "$0")" && pwd -P)
BASE=/mnt/weathercam/app
DEST=$BASE/releases/HarpendenWeatherCamera-V54.3
REC=/etc/weathercam/v54_3-rollback-target
python3 "$SRC/verify_v54_3.py"
if [ "$SRC" = "$DEST" ]; then
  echo "Run the installer from an extracted staging directory, not the active release."
  exit 1
fi
sudo mkdir -p "$BASE/releases" /etc/weathercam
INSTALL_CAMERA_UNIT=0
[ -f /etc/weathercam/dashboard.env ] || sudo install -m 0600 "$SRC/dashboard.env.example" /etc/weathercam/dashboard.env
if ! sudo systemctl cat weathercam.service >/dev/null 2>&1; then
  for unit_path in /etc/systemd/system/weathercam.service /run/systemd/system/weathercam.service /usr/local/lib/systemd/system/weathercam.service /usr/lib/systemd/system/weathercam.service /lib/systemd/system/weathercam.service; do
    if [ -e "$unit_path" ] || [ -L "$unit_path" ]; then
      echo "A weathercam.service unit file exists but is not registered; refusing to overwrite it."
      exit 1
    fi
  done
  if ! sudo grep -Eq '^HWS_FTP_PASSWORD=.+$' /etc/weathercam/dashboard.env; then
    echo "Set HWS_FTP_PASSWORD in /etc/weathercam/dashboard.env before installing the camera service."
    exit 1
  fi
  INSTALL_CAMERA_UNIT=1
fi
if [ -L "$BASE/current" ]; then
  PREVIOUS=$(readlink -f "$BASE/current")
elif [ -d "$BASE/current" ]; then
  PREVIOUS="$BASE/current-pre-v54.3-$(date +%Y%m%d-%H%M%S)"
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
python3 "$DEST/verify_v54_3.py"
sudo install -m 0644 "$DEST/systemd/weathercam-dashboard.service" /etc/systemd/system/weathercam-dashboard.service
sudo install -m 0644 "$DEST/systemd/weathercam-dashboard.timer" /etc/systemd/system/weathercam-dashboard.timer
if [ "$INSTALL_CAMERA_UNIT" -eq 1 ]; then
  sudo install -m 0644 "$DEST/systemd/weathercam.service" /etc/systemd/system/weathercam.service
fi
sudo install -m 0644 "$DEST/systemd/weathercam-weather-station.service" /etc/systemd/system/weathercam-weather-station.service
sudo rm -f "$BASE/current"
sudo ln -s "$DEST" "$BASE/current"
sudo systemctl daemon-reload
if [ "$INSTALL_CAMERA_UNIT" -eq 1 ]; then
  sudo systemctl enable weathercam.service
fi
sudo systemctl start weathercam.service
sleep 8
if ! systemctl is-active --quiet weathercam.service; then
  echo "Camera failed to start. Run sudo bash /mnt/weathercam/app/current/rollback_v54_3.sh"
  exit 1
fi
if sudo grep -Eq '^CLIENTRAW_URL=.+$' /etc/weathercam/dashboard.env; then
  sudo systemctl enable weathercam-weather-station.service
  sudo systemctl restart weathercam-weather-station.service
else
  echo "Weather station fetcher not started: set CLIENTRAW_URL in /etc/weathercam/dashboard.env, then run: sudo systemctl enable --now weathercam-weather-station.service"
fi
sudo -u mgs /usr/bin/python3 "$BASE/current/weathercam_dashboard/dashboard.py"
sudo systemctl enable --now weathercam-dashboard.timer
echo "Installed V54.3 -> $(readlink -f "$BASE/current")"
