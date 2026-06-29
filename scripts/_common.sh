#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
ENV_FILE="$PROJECT_ROOT/.env"

MODE=${BRICKY_MODE:-development}
if [ "${1:-}" = "--prod" ]; then
  MODE=production
  shift
fi

if [ "$MODE" = "production" ]; then
  COMPOSE_FILE="$PROJECT_ROOT/compose.prod.yaml"
else
  COMPOSE_FILE="$PROJECT_ROOT/compose.yaml"
fi

require_env() {
  if [ ! -f "$ENV_FILE" ]; then
    echo "error: $ENV_FILE is missing; copy .env.example first" >&2
    exit 1
  fi
}

compose() {
  docker compose \
    --project-directory "$PROJECT_ROOT" \
    --env-file "$ENV_FILE" \
    -f "$COMPOSE_FILE" \
    "$@"
}

service_running() {
  container_id=$(compose ps -q "$1")
  [ -n "$container_id" ] && [ "$(docker inspect -f '{{.State.Running}}' "$container_id")" = "true" ]
}

require_env
