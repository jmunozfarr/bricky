#!/bin/sh

set -eu
umask 077
for argument in "$@"; do
  if [ "$argument" = "--prod" ]; then
    BRICKY_MODE=production
    export BRICKY_MODE
  fi
done
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/_common.sh"

FORCE=0
ARCHIVE_INPUT=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    --prod) ;;
    -*) echo "error: unknown option $1" >&2; exit 2 ;;
    *)
      if [ -n "$ARCHIVE_INPUT" ]; then
        echo "error: provide exactly one backup archive" >&2
        exit 2
      fi
      ARCHIVE_INPUT=$1
      ;;
  esac
  shift
done

if [ "$FORCE" -ne 1 ] || [ -z "$ARCHIVE_INPUT" ]; then
  echo "usage: ./scripts/restore.sh [--prod] --force data/backups/bricky-TIMESTAMP.tar.gz" >&2
  echo "Restore replaces the current Bricky database and imported model files." >&2
  exit 2
fi

BACKUP_ROOT=$(CDPATH= cd -- "$PROJECT_ROOT/data/backups" && pwd -P)
ARCHIVE_ROOT=bricky-backup
ARCHIVE_DIR=$(CDPATH= cd -- "$(dirname -- "$ARCHIVE_INPUT")" && pwd -P)
ARCHIVE_NAME=$(basename -- "$ARCHIVE_INPUT")
if [ "$ARCHIVE_DIR" != "$BACKUP_ROOT" ] || [ ! -f "$BACKUP_ROOT/$ARCHIVE_NAME" ]; then
  echo "error: restore archives must be regular files under $BACKUP_ROOT" >&2
  exit 1
fi

RESTORE_NAME=".restore-$(date -u +%Y%m%dT%H%M%SZ)-$$"
RESTORE_ROOT="$BACKUP_ROOT/$RESTORE_NAME"
RUNNING_SERVICES=""

restart_services() {
  if [ -n "$RUNNING_SERVICES" ]; then
    compose start $RUNNING_SERVICES >/dev/null
  fi
}

cleanup() {
  if [ -n "${RESTORE_ROOT:-}" ] && [ -d "$RESTORE_ROOT" ]; then
    rm -rf -- "$RESTORE_ROOT"
  fi
  restart_services
}
trap cleanup EXIT HUP INT TERM

if ! service_running db; then
  echo "error: database service is not running" >&2
  exit 1
fi

echo "Validating backup format, paths, and SHA-256 checksums"
compose run --rm --no-deps api \
  python -m app.cli.backup prepare-restore \
  "/data/backups/$ARCHIVE_NAME" \
  --destination "/data/backups/$RESTORE_NAME" \
  --force

for service in api web; do
  if service_running "$service"; then
    RUNNING_SERVICES="$RUNNING_SERVICES $service"
  fi
done
if [ -n "$RUNNING_SERVICES" ]; then
  echo "Stopping application services before replacement"
  compose stop $RUNNING_SERVICES >/dev/null
fi

echo "Replacing PostgreSQL database"
compose exec -T db sh -c \
  'dropdb --force --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"'
compose exec -T db sh -c \
  'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$RESTORE_ROOT/$ARCHIVE_ROOT/database.dump"

echo "Applying current migrations"
compose run --rm --no-deps api alembic upgrade head

echo "Replacing imported model files"
compose run --rm --no-deps api \
  python -m app.cli.backup replace-models \
  --source "/data/backups/$RESTORE_NAME/$ARCHIVE_ROOT/models" \
  --destination /data/models

echo "Restore completed. LDraw library files were not part of the backup."
compose run --rm --no-deps api python -m app.cli.ldraw_library status || true
compose run --rm api python -m app.cli.ldraw_catalog status || true
echo "If the library is absent or the catalog reports stale, install/rebuild it explicitly."
