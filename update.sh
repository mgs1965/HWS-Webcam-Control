#!/bin/bash
# Update the camera to the latest GitHub release. The repository is private, so set GITHUB_TOKEN
# (a token with read access to contents) in /etc/weathercam/dashboard.env or the environment.
#   bash update.sh --check    show whether a newer release exists
#   bash update.sh            download, install, and roll back automatically if the camera does not start
set -euo pipefail
REPO=${HWS_UPDATE_REPO:-mgs1965/HWS-Webcam-Control}
BASE=/mnt/weathercam/app
if [ -z "${GITHUB_TOKEN:-}" ]; then
  GITHUB_TOKEN=$(sudo grep -E '^GITHUB_TOKEN=' /etc/weathercam/dashboard.env | head -1 | cut -d= -f2- || true)
fi
[ -n "${GITHUB_TOKEN:-}" ] || { echo "GITHUB_TOKEN is not set (needed because $REPO is private)."; exit 1; }
API=https://api.github.com/repos/$REPO/releases/latest
JSON=$(curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" "$API")
LATEST=$(printf '%s' "$JSON" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tag_name"])')
CURRENT=$(python3 -c 'import re,sys;print(re.search(r"VERSION=\"(V(?:[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]{2}|[0-9]+\.[0-9]+|[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2}))\"",open(sys.argv[1]).read()).group(1))' "$BASE/current/version.py" 2>/dev/null || echo none)
echo "Installed: $CURRENT   Latest: $LATEST"
LOGDIR=${HWS_LOG_DIR:-/mnt/weathercam/logs}
# The health page shows this as "last update check".
stamp_ok() {
  local f="$LOGDIR/update_last_ok.json" line
  line=$(printf '{"time": "%s", "version": "%s"}' "$(date -Is)" "$1")
  { printf '%s\n' "$line" > "$f" || printf '%s\n' "$line" | sudo -n tee "$f" > /dev/null; } 2> /dev/null || true
}
if [ "$CURRENT" = "$LATEST" ]; then stamp_ok "$CURRENT"; echo "Already up to date."; exit 0; fi
if [ "${1:-}" = "--check" ]; then echo "Update available."; exit 0; fi
ASSET_URL=$(printf '%s' "$JSON" | python3 -c 'import json,sys;a=[x for x in json.load(sys.stdin)["assets"] if x["name"].endswith(".zip")];print(a[0]["url"] if a else "")')
[ -n "$ASSET_URL" ] || { echo "Latest release has no zip asset."; exit 1; }
FAILED=$LOGDIR/update_failed
INSTALLING=1
STAGE=$(mktemp -d /tmp/hws-update.XXXXXX)
finish() {
  rc=$?
  rm -rf "$STAGE"
  if [ "$INSTALLING" = 1 ]; then
    if [ $rc -eq 0 ]; then rm -f "$FAILED" 2>/dev/null || true; stamp_ok "$LATEST"
    else echo "update to $LATEST failed (exit $rc) at $(date -Is); see /var/log/hws-update.log or journalctl -u weathercam-update" > "$FAILED" 2>/dev/null || true; fi
  fi
}
trap finish EXIT
curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/octet-stream" -o "$STAGE/release.zip" "$ASSET_URL"
unzip -q "$STAGE/release.zip" -d "$STAGE"
DIR=$(find "$STAGE" -maxdepth 2 -name install.sh -exec dirname {} \; | head -1)
[ -n "$DIR" ] || { echo "install.sh not found in the release."; exit 1; }
BEFORE=$(readlink -f "$BASE/current" 2>/dev/null || true)
if ! bash "$DIR/install.sh"; then
  AFTER=$(readlink -f "$BASE/current" 2>/dev/null || true)
  if [ "$AFTER" != "$BEFORE" ] || ! systemctl is-active --quiet weathercam.service; then
    echo "Install failed after switching releases; rolling back."
    bash "$BASE/current/rollback.sh"
  fi
  exit 1
fi
systemctl is-active --quiet weathercam.service || { echo "Camera not running after update; rolling back."; bash "$BASE/current/rollback.sh"; exit 1; }
echo "Updated to $LATEST"
