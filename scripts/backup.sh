#!/bin/sh

set -eu
umask 077
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/_common.sh"

BACKUP_ROOT="$PROJECT_ROOT/data/backups"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_NAME="bricky-$TIMESTAMP.tar.gz"
STAGING_NAME=".incomplete-$TIMESTAMP-$$"
STAGING="$BACKUP_ROOT/$STAGING_NAME"
OUTPUT="$BACKUP_ROOT/$BACKUP_NAME"
RUNNING_SERVICES=""

restart_services() {
  if [ -n "$RUNNING_SERVICES" ]; then
    compose start $RUNNING_SERVICES >/dev/null
  fi
}

cleanup() {
  if [ -n "${STAGING:-}" ] && [ -d "$STAGING" ]; then
    rm -rf -- "$STAGING"
  fi
  restart_services
}
trap cleanup EXIT HUP INT TERM

mkdir -p -- "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"

if ! service_running db; then
  echo "error: database service is not running" >&2
  exit 1
fi
compose exec -T db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null

for service in api web; do
  if service_running "$service"; then
    RUNNING_SERVICES="$RUNNING_SERVICES $service"
  fi
done
if [ -n "$RUNNING_SERVICES" ]; then
  echo "Pausing application writes for a consistent backup"
  compose stop $RUNNING_SERVICES >/dev/null
fi

mkdir -- "$STAGING"
echo "Creating PostgreSQL custom-format dump"
compose exec -T db sh -c \
  'pg_dump --format=custom --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "$STAGING/database.dump"

echo "Packaging database dump and immutable model originals"
compose run --rm --no-deps api \
  python -m app.cli.backup create \
  --dump "/data/backups/$STAGING_NAME/database.dump" \
  --models-root /data/models \
  --output "/data/backups/$BACKUP_NAME"

echo "Backup created: $OUTPUT"
sha256sum "$OUTPUT"
