#!/bin/sh

set -eu
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/_common.sh"

echo "Starting Bricky development stack on http://127.0.0.1:5173"
compose up --build -d
