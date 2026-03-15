#!/bin/bash
#
# Restart agent-hub services.
# Delegates to canonical rebuild.sh --restart (auto-detects Docker vs native).
#
set -eo pipefail
CANONICAL_SUMMITFLOW_ROOT="${SUMMITFLOW_BACKUP_ROOT:-$HOME/summitflow}"
exec bash "$CANONICAL_SUMMITFLOW_ROOT/scripts/rebuild.sh" --restart "$@"
