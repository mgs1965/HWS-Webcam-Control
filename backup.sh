#!/bin/bash
# Back up the data that cannot be rebuilt: the logs folder (news, weather and health history), the
# rollback record and, if HWS_BACKUP_INCLUDE_ENV=1, /etc/weathercam/dashboard.env (it holds secrets).
# Archives are kept in /mnt/weathercam/backups (last HWS_BACKUP_KEEP, default 14) and copied to
# HWS_BACKUP_DEST when set, e.g. user@nas:/volume1/hws-backups (rsync over ssh) or a mounted folder.
# Frames and *.log files are skipped. A failure leaves logs/backup_failed, which alerts.py reports.
set -euo pipefail
ROOT=${WEATHERCAM_ROOT:-/mnt/weathercam}
LOGS=${HWS_LOG_DIR:-$ROOT/logs}
OUT=${HWS_BACKUP_DIR:-$ROOT/backups}
KEEP=${HWS_BACKUP_KEEP:-14}
FAILED=$LOGS/backup_failed
trap 'rc=$?; [ $rc -eq 0 ] || echo "backup failed (exit $rc) at $(date -Is)" > "$FAILED" 2>/dev/null || true' EXIT
mkdir -p "$OUT"
NAME=hws-backup-$(date +%Y%m%d-%H%M%S).tar.gz
ITEMS=("$LOGS")
[ -f /etc/weathercam/rollback-target ] && ITEMS+=(/etc/weathercam/rollback-target)
[ "${HWS_BACKUP_INCLUDE_ENV:-0}" = 1 ] && [ -f /etc/weathercam/dashboard.env ] && ITEMS+=(/etc/weathercam/dashboard.env)
tar -czf "$OUT/$NAME" --exclude='*.log' --exclude='*.log.*' --exclude='*.jpg' --exclude='*.mp4' "${ITEMS[@]}"
tar -tzf "$OUT/$NAME" >/dev/null
if [ -n "${HWS_BACKUP_DEST:-}" ]; then
  case "$HWS_BACKUP_DEST" in
    *:*) rsync -a -e "ssh -o BatchMode=yes -o ConnectTimeout=20" "$OUT/$NAME" "$HWS_BACKUP_DEST/" ;;
    *) mkdir -p "$HWS_BACKUP_DEST" && cp "$OUT/$NAME" "$HWS_BACKUP_DEST/" ;;
  esac
fi
ls -1t "$OUT"/hws-backup-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
rm -f "$FAILED" 2>/dev/null || true
echo "Backup $NAME done${HWS_BACKUP_DEST:+, copied to $HWS_BACKUP_DEST}"
