#!/bin/bash
#
# Check agent-hub service status.
# Delegates to canonical rebuild.sh --status (auto-detects Docker vs native).
#
set -eo pipefail
CANONICAL_SUMMITFLOW_ROOT="${SUMMITFLOW_BACKUP_ROOT:-$HOME/summitflow}"
exec bash "$CANONICAL_SUMMITFLOW_ROOT/scripts/rebuild.sh" --status "$@"
