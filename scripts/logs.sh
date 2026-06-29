#!/bin/sh

set -eu
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/_common.sh"

compose logs -f api web db
