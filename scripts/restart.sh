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
for service in agent-hub-backend agent-hub-frontend agent-hub-celery neo4j; do
    if [ ! -L "${SYSTEMD_USER_DIR}/${service}.service" ]; then
        ln -sf "${SCRIPT_DIR}/systemd/${service}.service" "${SYSTEMD_USER_DIR}/"
    fi
done

# Reload systemd
systemctl --user daemon-reload

# Restart services (neo4j first since backend depends on it)
echo "Restarting neo4j..."
systemctl --user restart neo4j

# Wait for Neo4j to be ready
echo "Waiting for Neo4j..."
for i in {1..30}; do
    if curl -sf http://localhost:7474 > /dev/null 2>&1; then
        echo "Neo4j ready"
        break
    fi
    sleep 1
done

echo "Restarting agent-hub services..."
systemctl --user restart agent-hub-backend agent-hub-frontend

echo ""
echo "Services restarted. Check status with:"
echo "  ~/agent-hub/scripts/status.sh"
