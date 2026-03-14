#!/bin/bash
#
# Thin wrapper to the canonical SummitFlow backup implementation.
#

set -euo pipefail

CANONICAL_SUMMITFLOW_ROOT="${SUMMITFLOW_BACKUP_ROOT:-$HOME/summitflow}"

exec bash "$CANONICAL_SUMMITFLOW_ROOT/scripts/backup.sh" "$@"
