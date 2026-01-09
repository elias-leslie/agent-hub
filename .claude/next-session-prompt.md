# Agent Hub Frontend Production Readiness

## Context
Agent Hub frontend was updated to run in production mode (NODE_ENV=production).
Browser automation testing revealed several issues that need investigation and fixing.

## Critical Fixes Needed

### 1. API URL Pattern (HIGH PRIORITY)
Frontend uses hardcoded `http://localhost:8003` instead of relative paths.
This breaks when accessed via Cloudflare Tunnel (agent.summitflow.dev).

Files to fix:
- frontend/src/lib/api.ts - Change API_BASE to "" (empty string)
- frontend/src/hooks/use-provider-status.ts - Same fix

Pattern to follow (from Portfolio AI):
```typescript
// Before
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";
fetch(`${API_BASE}/status`)

// After  
fetch("/api/status")  // Let Next.js rewrites handle it
```

### 2. WebSocket URL Pattern (HIGH PRIORITY)
WebSocket URLs are hardcoded, breaking production access.

Files to fix:
- frontend/src/hooks/use-chat-stream.ts
- frontend/src/hooks/use-session-events.ts

Pattern to follow (from Terminal ~/terminal/frontend/lib/hooks/use-terminal-websocket.ts):
```typescript
// Before
const WS_URL = "ws://localhost:8003/api/stream";

// After
const getWsUrl = (path: string) => {
  if (typeof window === 'undefined') return `ws://localhost:8003${path}`;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
};
```

### 3. Standalone Output Warning
Next.js shows: "next start" does not work with "output: standalone"
Either:
- Remove `output: "standalone"` from next.config.ts, OR
- Change ExecStart to use `node .next/standalone/server.js`

Check what other projects use.

## Verification Steps After Fixes

1. Restart frontend: `systemctl --user restart agent-hub-frontend`
2. Test local: http://localhost:3003/dashboard (should load data)
3. Test production: https://agent.summitflow.dev/dashboard (should load data)
4. Test chat streaming works on both local and production
5. Check console for CORS errors

## Commands

```bash
# Check current status
systemctl --user status agent-hub-frontend agent-hub-backend

# View logs
journalctl --user -u agent-hub-frontend -f

# Restart after changes
systemctl --user restart agent-hub-frontend

# Test production with browser automation
node ~/.claude/skills/browser-automation/scripts/console.js https://agent.summitflow.dev/dashboard 5000
```

## Reference Projects
- ~/portfolio-ai/frontend - Uses relative /api/* paths
- ~/terminal/frontend - Uses dynamic WebSocket URL from window.location
- ~/summitflow/frontend - Reference for Next.js patterns
