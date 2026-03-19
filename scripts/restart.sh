#!/bin/bash
#
# Restart agent-hub services (full rebuild).
#
set -eo pipefail
exec bash "${SUMMITFLOW_BACKUP_ROOT:-$HOME/summitflow}/scripts/rebuild.sh" agent-hub "$@"
