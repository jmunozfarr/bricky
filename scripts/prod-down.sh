#!/bin/sh

set -eu
BRICKY_MODE=production
export BRICKY_MODE
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/_common.sh"

compose down
echo "Bricky production-like stack stopped; persistent data was preserved."
