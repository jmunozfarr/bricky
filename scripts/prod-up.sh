#!/bin/sh

set -eu
BRICKY_MODE=production
export BRICKY_MODE
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/_common.sh"

echo "Starting Bricky production-like stack"
compose up --build -d
compose ps
