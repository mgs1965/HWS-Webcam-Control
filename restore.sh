#!/bin/bash
# Restore a backup made by backup.sh (logs, rollback record, optionally the env file).
#   bash restore.sh --list                 list local backups
#   bash restore.sh --latest --dry-run     show what the newest backup would restore
#   sudo bash restore.sh --latest          restore the newest local backup (asks first)
#   sudo bash restore.sh /path/hws-backup-YYYYMMDD-HHMMSS.tar.gz --yes
# On a new SD card, fetch an archive first, e.g.
#   curl --user USER:PASS -o backup.tar.gz ftp://ftp.example.com/backups/hws-backup-....tar.gz
# dashboard.env is only restored with --with-env. HWS_RESTORE_ROOT changes the target (default /).
set -euo pipefail
ROOT=${WEATHERCAM_ROOT:-/mnt/weathercam}
DIR=${HWS_BACKUP_DIR:-$ROOT/backups}
TARGET=${HWS_RESTORE_ROOT:-/}
ARCHIVE=""; DRY=0; YES=0; ENV=0; LIST=0
for a in "$@"; do
  case "$a" in
    --list) LIST=1 ;;
    --latest) ARCHIVE=$(ls -1t "$DIR"/hws-backup-*.tar.gz 2>/dev/null | head -1 || true) ;;
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    --with-env) ENV=1 ;;
    -*) echo "Unknown option $a"; exit 2 ;;
    *) ARCHIVE=$a ;;
  esac
done
if [ $LIST = 1 ]; then ls -1t "$DIR"/hws-backup-*.tar.gz 2>/dev/null || echo "No backups in $DIR"; exit 0; fi
[ -n "$ARCHIVE" ] && [ -f "$ARCHIVE" ] || { echo "No archive given or found (try --list or --latest)."; exit 1; }
tar -tzf "$ARCHIVE" >/dev/null || { echo "$ARCHIVE is not a valid archive."; exit 1; }
EXCL=(--exclude=etc/weathercam/dashboard.env)
[ $ENV = 1 ] && EXCL=(--exclude=__none__)
if [ $DRY = 1 ]; then
  echo "Would restore from $ARCHIVE into $TARGET:"
  tar -tzf "$ARCHIVE" "${EXCL[@]}" | grep -v '/$' || true
  exit 0
fi
if [ $YES != 1 ]; then
  printf 'Restore %s into %s? Existing files will be overwritten. [y/N] ' "$ARCHIVE" "$TARGET"
  read -r ans; case "$ans" in y|Y|yes) ;; *) echo "Cancelled."; exit 1 ;; esac
fi
mkdir -p "$TARGET"
tar -xzpf "$ARCHIVE" -C "$TARGET" "${EXCL[@]}"
echo "Restored $ARCHIVE into $TARGET. Restart the services: sudo systemctl restart weathercam weathercam-dashboard"
