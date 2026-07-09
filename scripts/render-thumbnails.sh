#!/bin/sh

set -eu
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/_common.sh"

docker compose \
  --project-directory "$PROJECT_ROOT" \
  --env-file "$ENV_FILE" \
  -f "$PROJECT_ROOT/compose.yaml" \
  -f "$PROJECT_ROOT/compose.e2e.yaml" \
  --profile tools \
  run --rm thumbnails "$@"
