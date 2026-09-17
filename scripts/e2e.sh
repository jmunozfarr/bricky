#!/bin/sh

set -eu
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/_common.sh"

# Resolving the fixtures' official part references into a BOM needs an indexed
# catalog, so seed one before Playwright starts. Synthetic rather than the
# official archive: no network in an otherwise hermetic gate. The seed refuses
# when a catalog from a real library is already indexed, and never touches
# inventory -- see apps/api/tests/seed_e2e_catalog.py. Installing the official
# library stays a manual step, so the specs needing part geometry still skip.
#
# Pinned to compose.yaml like the run below: the development api image is the
# one carrying tests/, and the seed must target the same stack as the specs.
echo "Seeding the synthetic catalog the coverage specs assert against"
docker compose \
  --project-directory "$PROJECT_ROOT" \
  --env-file "$ENV_FILE" \
  -f "$PROJECT_ROOT/compose.yaml" \
  run --rm -e PYTHONPATH=. api python tests/seed_e2e_catalog.py

docker compose \
  --project-directory "$PROJECT_ROOT" \
  --env-file "$ENV_FILE" \
  -f "$PROJECT_ROOT/compose.yaml" \
  -f "$PROJECT_ROOT/compose.e2e.yaml" \
  --profile test \
  run --rm e2e
