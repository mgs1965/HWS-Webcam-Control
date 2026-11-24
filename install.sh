#!/bin/bash
set -euo pipefail
SRC=$(cd "$(dirname "$0")" && pwd -P)
BASE=/mnt/weathercam/app
VERSION=$(python3 -c "import re,sys;print(re.search(r'VERSION=\"(V(?:[0-9]{4}\\.[0-9]{2}\\.[0-9]{2}\\.[0-9]{2}|[0-9]+\\.[0-9]+|[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2}))\"',open(sys.argv[1]).read()).group(1))" "$SRC/version.py")
DEST=$BASE/releases/HarpendenWeatherCamera-$VERSION
REC=/etc/weathercam/rollback-target
python3 "$SRC/verify.py"
if [ "$SRC" = "$DEST" ] || { [ -L "$BASE/current" ] && [ "$SRC" = "$(readlink -f "$BASE/current")" ]; }; then
  echo "Run the installer from an extracted staging directory, not the active release."
  exit 1
fi
if [ -e "$DEST" ] || [ -L "$DEST" ]; then
  DEST="$DEST-$(date +%Y%m%d-%H%M%S)"
  [ ! -e "$DEST" ] && [ ! -L "$DEST" ] || { echo "Release already exists: $DEST"; exit 1; }
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
  PREVIOUS="$BASE/current-pre-install-$(date +%Y%m%d-%H%M%S)"
  sudo systemctl stop weathercam-dashboard.timer 2>/dev/null || true
  sudo systemctl stop weathercam.service 2>/dev/null || true
  sudo mv "$BASE/current" "$PREVIOUS"
else
  PREVIOUS=""
fi
[ -n "$PREVIOUS" ] && printf '%s\n' "$PREVIOUS" | sudo tee "$REC" >/dev/null
sudo systemctl stop weathercam-dashboard.timer 2>/dev/null || true
sudo systemctl stop weathercam.service 2>/dev/null || true
sudo cp -a "$SRC" "$DEST"
python3 "$DEST/verify.py"
sudo install -m 0644 "$DEST/systemd/weathercam-dashboard.service" /etc/systemd/system/weathercam-dashboard.service
sudo install -m 0644 "$DEST/systemd/weathercam-dashboard.timer" /etc/systemd/system/weathercam-dashboard.timer
if [ "$INSTALL_CAMERA_UNIT" -eq 1 ]; then
  sudo install -m 0644 "$DEST/systemd/weathercam.service" /etc/systemd/system/weathercam.service
fi
sudo install -m 0644 "$DEST/systemd/weathercam-weather-station.service" /etc/systemd/system/weathercam-weather-station.service
sudo install -m 0644 "$DEST/systemd/weathercam-alerts.service" /etc/systemd/system/weathercam-alerts.service
sudo install -m 0644 "$DEST/systemd/weathercam-alerts.timer" /etc/systemd/system/weathercam-alerts.timer
sudo install -m 0644 "$DEST/systemd/weathercam-update.service" /etc/systemd/system/weathercam-update.service
sudo install -m 0644 "$DEST/systemd/weathercam-update.timer" /etc/systemd/system/weathercam-update.timer
sudo install -m 0644 "$DEST/systemd/weathercam-backup.service" /etc/systemd/system/weathercam-backup.service
sudo install -m 0644 "$DEST/systemd/weathercam-backup.timer" /etc/systemd/system/weathercam-backup.timer
sudo rm -f "$BASE/current"
sudo ln -s "$DEST" "$BASE/current"
sudo systemctl daemon-reload
if [ "$INSTALL_CAMERA_UNIT" -eq 1 ]; then
  sudo systemctl enable weathercam.service
fi
sudo systemctl start weathercam.service
sleep 8
if ! systemctl is-active --quiet weathercam.service; then
  echo "Camera failed to start. Run sudo bash /mnt/weathercam/app/current/rollback.sh"
  exit 1
fi
if sudo grep -Eq '^HWS_METEOBRIDGE_URL=.+$' /etc/weathercam/dashboard.env; then
  sudo systemctl enable weathercam-weather-station.service
  sudo systemctl restart weathercam-weather-station.service
else
  echo "Weather station fetcher not started: set HWS_METEOBRIDGE_URL in /etc/weathercam/dashboard.env, then run: sudo systemctl enable --now weathercam-weather-station.service"
fi
if sudo grep -Eq '^HWS_ALERT_(NTFY_URL|WEBHOOK_URL|SMTP_HOST)=.+$' /etc/weathercam/dashboard.env; then
  sudo systemctl enable --now weathercam-alerts.timer
else
  echo "Health alerts not enabled: set HWS_ALERT_NTFY_URL (or webhook/SMTP) in /etc/weathercam/dashboard.env, then run: sudo systemctl enable --now weathercam-alerts.timer"
fi
if sudo grep -Eq '^HWS_AUTO_UPDATE=1$' /etc/weathercam/dashboard.env; then
  sudo systemctl enable --now weathercam-update.timer
else
  echo "Automatic updates not enabled: add HWS_AUTO_UPDATE=1 (and GITHUB_TOKEN=...) to /etc/weathercam/dashboard.env, then run: sudo systemctl enable --now weathercam-update.timer"
fi
if sudo grep -Eq '^HWS_BACKUP_DEST=.+$' /etc/weathercam/dashboard.env; then
  sudo systemctl enable --now weathercam-backup.timer
else
  echo "Backups not enabled: set HWS_BACKUP_DEST (user@host:/path or a mounted folder) in /etc/weathercam/dashboard.env, then run: sudo systemctl enable --now weathercam-backup.timer"
fi
sudo -u mgs /usr/bin/python3 "$BASE/current/weathercam_dashboard/dashboard.py" --import-news-archive
sudo -u mgs /usr/bin/python3 "$BASE/current/weathercam_dashboard/dashboard.py"
sudo systemctl enable --now weathercam-dashboard.timer
echo "Installed $VERSION -> $(readlink -f "$BASE/current")"
