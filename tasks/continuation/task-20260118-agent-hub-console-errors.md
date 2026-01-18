---
created: 2026-01-18T11:30:00-05:00
updated: 2026-01-18T12:20:00-05:00
status: in_progress
project: agent-hub
files_modified:
  - backend/app/adapters/gemini.py
---

# Agent Hub Console Errors Investigation

## Problem Statement

Agent Hub chat page (both Single and Roundtable modes) has console errors:
- 500 Internal Server Error
- "Failed to load chunk" errors
- Roundtable mode shows "Connecting..." and never becomes "Connected"

## Completed This Session

### 1. Gemini API Empty Response Fix - DONE

**Root Cause:** Gemini 3 Pro requires `thinking_config` to produce output, AND `max_output_tokens` must be larger than `thinking_budget` for actual response content to appear.

**Research Done:**
- Tested Gemini behavior: max_output_tokens=100 with thinking_budget=1024 returns empty
- Reviewed Claude official docs: min budget 1024, budget is target not strict limit
- Reviewed Auto-Claude patterns: low=1024, medium=4096, high=16384, ultrathink=65536
- Reviewed Automaker patterns: low=1024, medium=10000, high=16000, ultrathink=32000

**Fix Applied:** `backend/app/adapters/gemini.py`
- Set `min_effective_output = thinking_budget + 1024`
- If requested max_tokens is below this, bump it up automatically
- Applied to `complete()`, `stream()`, and `complete_with_tools()` methods

**Verified:** Gemini API now works correctly with small max_tokens requests.

## Outstanding Issue: Roundtable WebSocket

### Symptoms
- `/chat` page shows 500 errors in console
- Roundtable mode stuck on "Connecting..." placeholder
- Backend logs show session creation but no WebSocket connections from browser

### Investigation Done
- Backend session creation endpoint works: `POST /api/orchestration/roundtable` returns valid session
- `getApiBaseUrl()` and `getWsUrl()` correctly bundled in frontend
- Voice WebSocket connections work fine (same getWsUrl pattern)
- Frontend service running and responding to HTTP

### Code Analysis

**Session creation in `page.tsx` (lines 516-540):**
```javascript
const createSession = async () => {
  if (sessionId) return;
  const res = await fetch(`${getApiBaseUrl()}/api/orchestration/roundtable`, {...});
  if (res.ok) { setSessionId(data.id); }
  // No else clause - silent failure if res is NOT ok
};
```

**Hook connection in `use-roundtable.ts`:**
```javascript
useRoundtable({ sessionId: sessionId ?? "", autoConnect: !!sessionId });
// If sessionId stays null, autoConnect is false, WebSocket never connects
```

### Suspected Issues (Need Browser DevTools)

1. **Silent session creation failure** - No error handling for non-OK responses
2. **Race condition** - Hook might evaluate before session creation completes
3. **Build/cache issue** - "Failed to load chunk" suggests possible Next.js caching problem

## Next Steps for Fresh Session

1. **Browser DevTools Investigation**
   - Open DevTools Network tab, filter to XHR/Fetch
   - Navigate to /chat, switch to Roundtable mode
   - Check if POST to `/api/orchestration/roundtable` succeeds
   - Check if WebSocket connection is attempted

2. **If session creation fails:**
   - Add error handling to `createSession()` in page.tsx
   - Surface error to UI instead of silent failure

3. **If session creates but WebSocket doesn't connect:**
   - Verify WebSocket URL is correct in browser console
   - Check backend logs for connection attempts
   - Verify roundtable router has WebSocket endpoint

4. **If chunk loading errors:**
   - Full rebuild: `./scripts/rebuild.sh --frontend`
   - Clear browser cache

## Files to Investigate

- `/home/kasadis/agent-hub/frontend/src/app/chat/page.tsx` (RoundtableChat component)
- `/home/kasadis/agent-hub/frontend/src/hooks/use-roundtable.ts`
- `/home/kasadis/agent-hub/backend/app/routers/orchestration.py`

## Resume Command

```
/do_it /home/kasadis/agent-hub/tasks/continuation/task-20260118-agent-hub-console-errors.md
```

Focus on browser DevTools investigation to capture actual network failures.
