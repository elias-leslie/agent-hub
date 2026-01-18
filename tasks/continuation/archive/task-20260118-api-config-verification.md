# Continuation: API Config Pattern Verification

**Created:** 2026-01-18
**Status:** Ready to verify
**Priority:** P1 (testing implementation from previous session)

---

## Context

Previous session implemented per-project `lib/api-config.ts` pattern across all 4 frontends:
- **terminal** - P0 fix for broken production REST API
- **agent-hub** - Consolidated 3 inconsistent WS patterns
- **summitflow** - Fixed hardcoded voice URL
- **portfolio-ai** - Removed Next.js rewrites, standardized pattern

All code changes committed: `55e09d5`, `d4ffd7c`, `1a45a8a7`, `29f3256f`

---

## Verification Tasks

### Phase 1: Local Development Testing

For each project, verify:
- [ ] Dev mode works (localhost detection)
- [ ] API calls reach correct backend port
- [ ] WebSocket connections work

```bash
# Start services
bash ~/agent-hub/scripts/restart.sh
bash ~/summitflow/scripts/restart.sh
bash ~/terminal/scripts/restart.sh
bash ~/portfolio-ai/scripts/restart.sh
```

### Phase 2: Browser Automation Testing

Use `ba` CLI to check all sites for console errors:

```bash
# Agent Hub
ba check http://localhost:3003 --no-errors -o /tmp/verify/agent-hub

# Terminal
ba check http://localhost:3002 --no-errors -o /tmp/verify/terminal

# SummitFlow
ba check http://localhost:3001 --no-errors -o /tmp/verify/summitflow

# Portfolio-AI
ba check http://localhost:3000 --no-errors -o /tmp/verify/portfolio-ai
```

### Phase 3: Production Testing (Cloudflare Tunnels)

Test actual production URLs via ba with Cloudflare auth:

```bash
# Agent Hub
ba check https://agent.summitflow.dev --no-errors -o /tmp/verify/prod-agent-hub

# Terminal
ba check https://terminal.summitflow.dev --no-errors -o /tmp/verify/prod-terminal

# SummitFlow
ba check https://dev.summitflow.dev --no-errors -o /tmp/verify/prod-summitflow

# Portfolio-AI
ba check https://port.summitflow.dev --no-errors -o /tmp/verify/prod-portfolio
```

### Phase 4: Feature-Specific Testing

| Feature | Test |
|---------|------|
| Terminal REST API | Create/list sessions, panes work in prod |
| Terminal WebSocket | Connect and type in terminal |
| Agent Hub chat | Send message, verify streaming works |
| SummitFlow execution | Task execution WebSocket connects |
| Portfolio-AI watchlist | API calls return data |
| Voice (all projects) | Verify graceful degradation when agent-hub unavailable |

---

## Potential Issues

1. **CORS** - May need backend CORS config updates for cross-origin requests
2. **Cloudflare Access** - Production sites may need auth headers for ba
3. **Missing env vars** - NEXT_PUBLIC_VOICE_URL may need setting in production

---

## Files Modified (Reference)

### agent-hub/frontend/
- `src/lib/api-config.ts` (new)
- `src/hooks/use-chat-stream.ts`
- `src/hooks/use-roundtable.ts`
- `src/hooks/use-session-events.ts`
- `next.config.ts`

### terminal/frontend/
- `lib/api-config.ts` (new)
- `lib/hooks/use-terminal-websocket.ts`
- `lib/hooks/use-terminal-sessions.ts`
- `lib/hooks/use-terminal-panes.ts`
- `lib/hooks/use-project-settings.ts`
- `lib/hooks/use-claude-polling.ts`
- `lib/hooks/use-project-terminals.ts`
- `lib/hooks/use-terminal-tabs-state.ts`
- `lib/hooks/use-prompt-cleaner.ts`
- `next.config.ts`

### summitflow/frontend/
- `lib/api-config.ts` (new)
- `components/VoiceOverlayWrapper.tsx` (new)
- `hooks/useExecutionWebSocket.ts`
- `components/tasks/ExecutionTimeline.tsx`
- `app/layout.tsx`
- `next.config.ts`

### portfolio-ai/frontend/
- `lib/api-config.ts` (new)
- `components/VoiceOverlayWrapper.tsx` (new)
- `lib/api/client.ts`
- `components/status/SourceQualityCard.tsx`
- `components/rules/RulesViewer.tsx`
- `lib/api/status.ts`
- `app/layout.tsx`
- `next.config.ts`

---

## Resume Command

```
/do_it /home/kasadis/agent-hub/tasks/continuation/task-20260118-api-config-verification.md
```
