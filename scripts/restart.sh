#!/bin/bash
# Restart agent-hub services
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

# Ensure systemd user directory exists
mkdir -p "${SYSTEMD_USER_DIR}"

# Link service files if not already linked
for service in agent-hub-backend agent-hub-frontend agent-hub-celery; do
    if [ ! -L "${SYSTEMD_USER_DIR}/${service}.service" ]; then
        ln -sf "${SCRIPT_DIR}/systemd/${service}.service" "${SYSTEMD_USER_DIR}/"
    fi
done

# Reload systemd
systemctl --user daemon-reload

# Restart services
systemctl --user restart agent-hub-backend agent-hub-frontend

echo "Services restarted. Check status with:"
echo "  systemctl --user status agent-hub-backend agent-hub-frontend"
