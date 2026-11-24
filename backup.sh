#!/bin/bash
# Back up the data that cannot be rebuilt: the logs folder (news, weather and health history), the
# rollback record and, if HWS_BACKUP_INCLUDE_ENV=1, /etc/weathercam/dashboard.env (it holds secrets).
# Archives are kept in /mnt/weathercam/backups (last HWS_BACKUP_KEEP, default 14) and copied to
# HWS_BACKUP_DEST when set, e.g. user@nas:/volume1/hws-backups (rsync over ssh), a mounted folder, or
# ftp://host/dir/ (plain FTP via curl, with HWS_BACKUP_FTP_USER / HWS_BACKUP_FTP_PASSWORD).
# A second destination can be set in HWS_BACKUP_DEST2 (FTP login: HWS_BACKUP_FTP2_USER / _PASSWORD).
# Both are attempted even if one fails; any failure raises the backup alert.
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
# tar exits 1 when a file changed while it was read (the logs are live); that is only a warning.
rc=0
tar -czf "$OUT/$NAME" --exclude='*.log' --exclude='*.log.*' --exclude='*.jpg' --exclude='*.mp4' "${ITEMS[@]}" || rc=$?
[ $rc -le 1 ] || exit $rc
tar -tzf "$OUT/$NAME" >/dev/null
esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
send() {  # $1 destination, $2 FTP user, $3 FTP password
  case "$1" in
    ftp://*)
      # Plain FTP. Credentials go to curl on stdin so they never show in the process list.
      TLS=(--no-sessionid); [ "${HWS_BACKUP_FTP_TLS:-0}" = 1 ] && TLS=(--ssl-reqd)
      printf 'user = "%s:%s"\n' "$(esc "$2")" "$(esc "$3")" |
        curl -sS --fail --ftp-create-dirs --connect-timeout 30 --max-time 1800 "${TLS[@]}" -K - -T "$OUT/$NAME" "${1%/}/$NAME" ;;
    *:*) rsync -a -e "ssh -o BatchMode=yes -o ConnectTimeout=20" "$OUT/$NAME" "$1/" ;;
    *) mkdir -p "$1" && cp "$OUT/$NAME" "$1/" ;;
  esac
}
SENT=""; BAD=0
if [ -n "${HWS_BACKUP_DEST:-}" ]; then
  if send "$HWS_BACKUP_DEST" "${HWS_BACKUP_FTP_USER:-}" "${HWS_BACKUP_FTP_PASSWORD:-}"; then SENT=$HWS_BACKUP_DEST; else BAD=1; fi
fi
if [ -n "${HWS_BACKUP_DEST2:-}" ]; then
  if send "$HWS_BACKUP_DEST2" "${HWS_BACKUP_FTP2_USER:-}" "${HWS_BACKUP_FTP2_PASSWORD:-}"; then SENT="${SENT:+$SENT, }$HWS_BACKUP_DEST2"; else BAD=1; fi
fi
if [ $BAD -ne 0 ]; then echo "copy to a backup destination failed" >&2; exit 1; fi
ls -1t "$OUT"/hws-backup-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
rm -f "$FAILED" 2>/dev/null || true
echo "Backup $NAME done${SENT:+, copied to $SENT}"
