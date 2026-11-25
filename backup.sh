#!/bin/bash
# Back up the data that cannot be rebuilt: the logs folder (news, weather and health history), the
# rollback record and, if HWS_BACKUP_INCLUDE_ENV=1, /etc/weathercam/dashboard.env (it holds secrets).
# Archives are kept in /mnt/weathercam/backups (last HWS_BACKUP_KEEP, default 14) and copied to
# HWS_BACKUP_DEST when set, e.g. user@nas:/volume1/hws-backups (rsync over ssh), a mounted folder, or
# ftp://host/dir/ (plain FTP via curl, with HWS_BACKUP_FTP_USER / HWS_BACKUP_FTP_PASSWORD).
# A second destination can be set in HWS_BACKUP_DEST2 (FTP login: HWS_BACKUP_FTP2_USER / _PASSWORD).
# Both are attempted even if one fails; any failure raises the backup alert.
# HWS_BACKUP_REMOTE_KEEP_DAYS=N also deletes this script's archives older than N days from the destinations
# (off by default). Restore with restore.sh.
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
creds() { printf 'user = "%s:%s"\n' "$(esc "$1")" "$(esc "$2")"; }  # fed to curl on stdin so the password never shows in ps
dest_url() { case "$1" in ftp.*) printf 'ftp://%s' "$1" ;; *) printf '%s' "$1" ;; esac; }  # host given without ftp://
hide_login() { sed -E 's#(://)[^/@]*@#\1#'; }
set_tls() { TLS=(--no-sessionid); if [ "${HWS_BACKUP_FTP_TLS:-0}" = 1 ] || [ "${1#ftps://}" != "$1" ]; then TLS=(--ssl-reqd); fi; }
send() {  # $1 destination, $2 FTP user, $3 FTP password
  case "$1" in
    ftp://*|ftps://*)
      set_tls "$1"
      creds "$2" "$3" | curl -sS --fail --ftp-create-dirs --connect-timeout 30 --max-time 1800 "${TLS[@]}" -K - -T "$OUT/$NAME" "${1%/}/$NAME" ;;
    *:*) rsync -a -e "ssh -o BatchMode=yes -o ConnectTimeout=20" "$OUT/$NAME" "$1/" ;;
    *) mkdir -p "$1" && cp "$OUT/$NAME" "$1/" ;;
  esac
}
# Remote pruning: HWS_BACKUP_REMOTE_KEEP_DAYS=N removes this script's own archives older than N days from the
# destination (judged by the date in the file name). Off when unset or 0. A pruning problem is only a warning.
KEEP_DAYS=${HWS_BACKUP_REMOTE_KEEP_DAYS:-0}
cutoff() { date -d "-$KEEP_DAYS days" +%Y%m%d 2>/dev/null || date -v-"${KEEP_DAYS}"d +%Y%m%d; }
expired() {  # names on stdin -> the ones older than the cutoff
  local c n d; c=$(cutoff)
  { grep -E '^hws-backup-[0-9]{8}-[0-9]{6}\.tar\.gz$' || true; } | while read -r n; do
    d=${n#hws-backup-}; if [ "${d%%-*}" -lt "$c" ]; then echo "$n"; fi
  done
}
prune() {  # $1 destination, $2 FTP user, $3 FTP password
  [ "$KEEP_DAYS" -gt 0 ] 2>/dev/null || return 0
  local rest host dir scheme names n host_ssh path
  case "$1" in
    ftp://*|ftps://*)
      scheme=${1%%://*}; rest=${1#*://}; host=${rest%%/*}; dir=${rest#"$host"}; dir=${dir#/}; dir=${dir%/}
      set_tls "$1"
      names=$(creds "$2" "$3" | curl -sS --list-only --connect-timeout 30 "${TLS[@]}" -K - "$scheme://$host/${dir:+$dir/}" | tr -d '\r' | sed 's#.*/##') || return 1
      for n in $(printf '%s\n' "$names" | expired); do
        creds "$2" "$3" | curl -sS --connect-timeout 30 "${TLS[@]}" -K - -o /dev/null -Q "-DELE ${dir:+$dir/}$n" "$scheme://$host/" && echo "Removed old remote backup $n"
      done ;;
    *:*)
      host_ssh=${1%%:*}; path=${1#*:}
      names=$(ssh -o BatchMode=yes -o ConnectTimeout=20 "$host_ssh" "ls -1 -- $(printf '%q' "$path")") || return 1
      for n in $(printf '%s\n' "$names" | expired); do
        ssh -o BatchMode=yes -o ConnectTimeout=20 "$host_ssh" "rm -f -- $(printf '%q' "${path%/}/$n")" && echo "Removed old remote backup $n"
      done ;;
    *)
      for n in $(ls -1 "$1" 2>/dev/null | expired); do rm -f "$1/$n" && echo "Removed old remote backup $n"; done ;;
  esac
}
SENT=""; BAD=0
for slot in "" 2; do
  eval "dest=\${HWS_BACKUP_DEST$slot:-}; user=\${HWS_BACKUP_FTP${slot}_USER:-}; pass=\${HWS_BACKUP_FTP${slot}_PASSWORD:-}"
  [ -n "$dest" ] || continue
  dest=$(dest_url "$dest")
  if send "$dest" "$user" "$pass"; then
    SENT="${SENT:+$SENT, }$(printf '%s' "$dest" | hide_login)"
    prune "$dest" "$user" "$pass" || echo "warning: could not prune old backups at $(printf '%s' "$dest" | hide_login)" >&2
  else
    BAD=1
  fi
done
if [ $BAD -ne 0 ]; then echo "copy to a backup destination failed" >&2; exit 1; fi
ls -1t "$OUT"/hws-backup-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
rm -f "$FAILED" 2>/dev/null || true
# The health page shows this as "last backup".
{ printf '{"time": "%s", "name": "%s", "size_bytes": %s, "destinations": "%s"}\n' "$(date -Is)" "$NAME" "$(wc -c < "$OUT/$NAME" | tr -d ' ')" "$SENT" > "$LOGS/backup_last_ok.json"; } 2>/dev/null || true
echo "Backup $NAME done${SENT:+, copied to $SENT}"
