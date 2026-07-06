#!/bin/sh

set -eu
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/_common.sh"

echo "Validating Compose configuration"
compose config --quiet

echo "Starting development services required by checks"
compose up --build -d db api web

echo "Linting Python sources"
compose exec -T api ruff check .
compose exec -T api ruff format --check .

echo "Type-checking Python sources"
compose exec -T api mypy app tests

echo "Running API tests"
compose exec -T api pytest -q

echo "Checking generated API types against the running schema"
compose exec -T web npm run check:api-types

echo "Linting frontend sources"
compose exec -T web npm run lint

echo "Checking frontend formatting"
compose exec -T web npm run format:check

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
