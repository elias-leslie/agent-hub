---
created: 2026-01-18T11:30:00-05:00
status: in_progress
project: agent-hub
files_modified:
  - (none yet for this issue)
---

# Agent Hub Console Errors Investigation

## Problem Statement

Agent Hub chat page (both Single and Roundtable modes) has console errors:
- 500 Internal Server Error
- "Failed to load chunk" errors
- Roundtable mode shows "Connecting..." and never becomes "Connected"

## What Was Fixed This Session

1. **Portfolio-AI CLAUDE_SONNET import** - FIXED
   - Created `backend/app/constants/models.py` with model constants
   - Updated `backend/app/constants/__init__.py` to export them
   - Deleted shadowed `backend/app/constants.py`

2. **Terminal WebSocket disconnect loop** - FIXED
   - Removed `wsRef.current?.send` and `wsRef.current?.readyState` from useEffect deps
   - Fixed session-switch validation to allow empty `from_session`

## Outstanding Issue: Agent Hub Console Errors

### Symptoms
- `/chat` page shows 500 errors in console
- Roundtable mode stuck on "Connecting..." placeholder
- Single mode shows "Ready" but may have transient errors

### Investigation Done
- Backend endpoints work via curl (session creation, WebSocket handshake)
- `getApiBaseUrl()` and `getWsUrl()` correctly bundled
- Backend logs show no roundtable WebSocket connections from browser
- Voice WebSocket connections work fine

### Suspected Root Causes (needs Gemini Pro consultation)

1. **Session creation may silently fail** - No error handling for non-OK responses:
   ```javascript
   // page.tsx line ~530
   if (res.ok) { setSessionId(data.id); }
   // No else clause - silent failure
   ```

2. **useRoundtable hook may not connect** - If sessionId is empty:
   ```javascript
   autoConnect: !!sessionId  // false if sessionId is empty
   ```

3. **JavaScript chunk loading errors** - Suggests possible build/cache issue

### Next Steps for Fresh Session

1. **Consult /ask_gemini pro** about:
   - Best practices for React WebSocket hooks with session creation
   - How to debug silent fetch failures
   - Proper error handling patterns

2. **Full rebuild sequence**:
   ```bash
   cd ~/agent-hub/frontend
   rm -rf .next node_modules/.cache
   npm run build
   systemctl --user restart agent-hub-frontend
   ```

3. **Add error handling** to session creation:
   ```javascript
   if (!res.ok) {
     console.error("Session creation failed:", res.status);
     setError(`Failed to create session: ${res.status}`);
   }
   ```

4. **Test with browser DevTools open** to capture actual network failures

5. **Check backend orchestration router** for any missing endpoints or errors

## Files to Investigate

- `/home/kasadis/agent-hub/frontend/src/app/chat/page.tsx` (RoundtableSection)
- `/home/kasadis/agent-hub/frontend/src/hooks/use-roundtable.ts`
- `/home/kasadis/agent-hub/backend/app/routers/orchestration.py`

## Resume Command

```
/do_it /home/kasadis/agent-hub/tasks/continuation/task-20260118-agent-hub-console-errors.md
```

Then immediately: `/ask_gemini pro` about the suspected root causes above.
