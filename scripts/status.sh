#!/bin/bash
# Check agent-hub service status
set -euo pipefail

echo "=== agent-hub Service Status ==="
echo

for service in agent-hub-backend agent-hub-frontend agent-hub-celery; do
    echo "--- ${service} ---"
    systemctl --user status "${service}" --no-pager 2>/dev/null | head -5 || echo "Not installed/running"
    echo
done

echo "=== Port Check ==="
netstat -tlnp 2>/dev/null | grep -E ':800[0-9]|:300[0-9]' || ss -tlnp 2>/dev/null | grep -E ':800[0-9]|:300[0-9]' || echo "No relevant ports found"
