#!/bin/bash
# Check agent-hub service status
set -euo pipefail

echo "=== agent-hub Service Status ==="
echo

for service in neo4j agent-hub-backend agent-hub-frontend agent-hub-celery; do
    echo "--- ${service} ---"
    systemctl --user status "${service}" --no-pager 2>/dev/null | head -5 || echo "Not installed/running"
    echo
done

echo "=== Port Check ==="
ss -tlnp 2>/dev/null | grep -E ':800[0-9]|:300[0-9]|:7474|:7687' || echo "No relevant ports found"

echo ""
echo "=== Health Endpoints ==="
echo -n "Backend:  "
curl -sf http://localhost:8003/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status', 'unknown'))" 2>/dev/null || echo "unreachable"

echo -n "Neo4j:    "
curl -sf http://localhost:7474 > /dev/null 2>&1 && echo "healthy" || echo "unreachable"

echo -n "Frontend: "
curl -sf http://localhost:3003 > /dev/null 2>&1 && echo "healthy" || echo "unreachable"
