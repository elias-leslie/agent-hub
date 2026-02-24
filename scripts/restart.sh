#!/bin/bash
# Restart agent-hub services
set -euo pipefail

# Symlink-safe script directory resolution
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

# Ensure systemd user directory exists
mkdir -p "${SYSTEMD_USER_DIR}"

# Link service files if not already linked
for service in agent-hub-backend agent-hub-frontend agent-hub-hatchet-worker; do
    if [ ! -L "${SYSTEMD_USER_DIR}/${service}.service" ]; then
        ln -sf "${SCRIPT_DIR}/systemd/${service}.service" "${SYSTEMD_USER_DIR}/"
    fi
done

# Reload systemd
systemctl --user daemon-reload

echo "Ensuring Hatchet engine is running..."
if ! systemctl --user is-active --quiet hatchet-engine; then
    systemctl --user start hatchet-engine
    sleep 5
else
    echo "Hatchet engine already running (skipping restart to preserve auth tokens)"
fi

echo "Restarting agent-hub services..."
systemctl --user restart agent-hub-backend agent-hub-frontend agent-hub-hatchet-worker

echo ""
echo "Services restarted. Check status with:"
echo "  ~/agent-hub/scripts/status.sh"
