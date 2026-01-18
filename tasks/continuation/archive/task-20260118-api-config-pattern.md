# Continuation: Frontend-Backend API Configuration Pattern

**Created:** 2026-01-18
**Completed:** 2026-01-18
**Status:** Completed
**Priority:** P0 (terminal REST is broken in production)

---

## Context

Comprehensive analysis of frontend-backend URL configuration across all 4 projects revealed:
- Hardcoded localhost URLs in next.config.ts (broken in production)
- Inconsistent WebSocket URL construction patterns
- No standard approach for dev vs production URL handling

## Architecture Decision

**Decision:** Per-project self-contained `lib/api-config.ts` (NOT a shared package)

**Rationale:**
- Each project should be standalone/independent
- Agent-hub integration is opt-in, not required
- Cross-project knowledge creates unwanted coupling
- Users downloading a single project (e.g., portfolio-ai) shouldn't need agent-hub for core functionality

## Implementation Plan

### Phase 1: Create Standard Pattern

Create `lib/api-config.ts` in each frontend with:

```typescript
// Example for portfolio-ai (adjust ports/domains per project)
const PORTS = { frontend: 3000, backend: 8000 };
const PROD_DOMAIN = 'port.summitflow.dev';
const PROD_API_DOMAIN = 'portapi.summitflow.dev';

export function getApiBaseUrl(): string {
  if (typeof window === 'undefined') return `http://localhost:${PORTS.backend}`;

  const host = window.location.hostname;
  if (host === 'localhost' || host === '127.0.0.1') {
    return `http://localhost:${PORTS.backend}`;
  }
  if (host === PROD_DOMAIN) {
    return `https://${PROD_API_DOMAIN}`;
  }

  return `http://localhost:${PORTS.backend}`;
}

export function getWsUrl(path: string): string {
  const base = getApiBaseUrl();
  return base.replace(/^http/, 'ws') + path;
}
```

### Phase 2: Per-Project Implementation

| Project | Frontend Port | Backend Port | Prod Frontend | Prod Backend |
|---------|---------------|--------------|---------------|--------------|
| agent-hub | 3003 | 8003 | agent.summitflow.dev | agentapi.summitflow.dev |
| summitflow | 3001 | 8001 | dev.summitflow.dev | devapi.summitflow.dev |
| portfolio-ai | 3000 | 8000 | port.summitflow.dev | portapi.summitflow.dev |
| terminal | 3002 | 8002 | terminal.summitflow.dev | terminalapi.summitflow.dev |

### Phase 3: Update Existing Code

For each project:
1. Create `lib/api-config.ts` with project-specific values
2. Update all API calls to use `getApiBaseUrl()`
3. Update all WebSocket connections to use `getWsUrl()`
4. Remove hardcoded localhost references
5. Make agent-hub integration conditional via env vars

### Phase 4: Cross-Project Integration (Opt-In)

For projects that want agent-hub features:
```typescript
// lib/external-services.ts
export function getAgentHubUrl(): string | null {
  return process.env.NEXT_PUBLIC_AGENT_HUB_URL || null;
}

export function getVoiceUrl(): string | null {
  return process.env.NEXT_PUBLIC_VOICE_URL || null;
}
```

VoiceOverlay becomes conditional:
```typescript
const VOICE_URL = process.env.NEXT_PUBLIC_VOICE_URL;
{VOICE_URL && <VoiceOverlay wsUrl={VOICE_URL} />}
```

### Phase 5: Documentation

**IMPORTANT:** After implementation, run `/claude_it` to:
1. Document the pattern in global rules
2. Create project-specific rules if needed
3. Ensure all projects and future projects follow this pattern

## Files to Modify

### agent-hub/frontend/
- [x] Create `lib/api-config.ts`
- [x] Update `hooks/use-chat-stream.ts` (remove getWsUrl, use shared)
- [x] Update `hooks/use-roundtable.ts` (remove getWsUrl, use shared)
- [x] Update `hooks/use-session-events.ts` (remove getWsUrl, use shared)
- [x] Removed next.config.ts rewrites

### summitflow/frontend/
- [x] Create `lib/api-config.ts`
- [x] Update `hooks/useExecutionWebSocket.ts`
- [x] Update `components/tasks/ExecutionTimeline.tsx`
- [x] Make VoiceOverlay conditional in `app/layout.tsx` (via VoiceOverlayWrapper)

### portfolio-ai/frontend/
- [x] Create `lib/api-config.ts`
- [x] Update `lib/api/client.ts`
- [x] Make VoiceOverlay conditional in `app/layout.tsx` (via VoiceOverlayWrapper)
- [x] Update hardcoded fetch calls (SourceQualityCard, RulesViewer, status.ts)
- [x] Removed next.config.ts rewrites

### terminal/frontend/
- [x] Create `lib/api-config.ts`
- [x] Update `lib/hooks/use-terminal-websocket.ts`
- [x] Update `lib/hooks/use-prompt-cleaner.ts` (make agent-hub optional)
- [x] Update all REST API hooks (use-terminal-sessions, use-terminal-panes, etc.)
- [x] Removed next.config.ts rewrites

## Priority Order

1. **terminal** - REST API completely broken in production (P0)
2. **agent-hub** - 3 inconsistent WS patterns causing dev confusion (P1)
3. **summitflow** - Hardcoded voice URL (P1)
4. **portfolio-ai** - Works but inconsistent (P2)

## Verification

After each project:
1. `dt --check` passes
2. Dev mode works (localhost detection)
3. Production mode works (domain detection)
4. WebSocket connections work in both modes
5. Optional features degrade gracefully when env vars not set

## Resume Command

```
/do_it /home/kasadis/agent-hub/tasks/continuation/task-20260118-api-config-pattern.md
```

## Post-Implementation

**Run `/claude_it` to document:**
1. The per-project api-config pattern
2. Environment variable conventions for cross-project integration
3. How to make agent-hub features optional/conditional
4. Standalone deployment requirements

This ensures all projects and future projects follow the same pattern.

---

## Reference: Gemini Analysis Summary

Gemini Pro recommended:
- Separate `@agent-hub/api-config` package (we rejected this for independence)
- Environment variables with runtime detection (we adopted the detection part)
- Centralized API client (each project has its own)

Our adaptation prioritizes project independence while maintaining consistent patterns.

## Reference: Cloudflare Tunnel Architecture

Production uses Cloudflare Tunnels (NOT nginx):
- Each subdomain routes to localhost port
- Frontend and backend on different subdomains (cross-origin)
- CORS already configured in backends
- No reverse proxy to same-origin
