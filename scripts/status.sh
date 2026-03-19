#!/bin/bash
#
# Check agent-hub service status.
#
set -eo pipefail
exec bash "${SUMMITFLOW_BACKUP_ROOT:-$HOME/summitflow}/scripts/rebuild.sh" --status agent-hub "$@"
