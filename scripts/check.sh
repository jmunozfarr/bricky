#!/bin/sh

set -eu
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/_common.sh"

echo "Validating Compose configuration"
compose config --quiet

echo "Starting development services required by checks"
compose up --build -d db api web

echo "Running API tests"
compose exec -T api pytest -q

echo "Running frontend tests"
compose exec -T web npm run test

echo "Running strict TypeScript checks"
compose exec -T web npm run typecheck

echo "Building frontend production assets"
compose exec -T web npm run build

echo "Checking frontend bundle budgets"
compose exec -T web npm run check:bundle

echo "Running browser and accessibility checks"
"$SCRIPT_DIR/e2e.sh"

echo "All Bricky checks passed."
