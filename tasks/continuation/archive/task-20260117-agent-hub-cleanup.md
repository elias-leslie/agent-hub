# Continuation: Agent Hub Cleanup & Test Fixes

**Date:** 2026-01-17
**Context:** Post-memory testing session, quality gate failures remain
**Previous Session:** Verified P1 (fire-and-forget) and P2 (memory context) fixes

## Session Summary

Previous session completed verification testing for memory integration fixes. Remaining work items need completion.

### Completed This Session
- [x] P1 verification: Fire-and-forget voice response (code review verified)
- [x] P2 verification: Memory context utilization (tests passed after bug fix)
- [x] T3.1: Voice + Memory integration test
- [x] Gemini Pro review of both fixes
- [x] Bug fix: Memory context was injected into `messages_dict` but `all_messages` was passed to adapter

### Bug Fixed
**Memory context not reaching model** - `backend/app/api/complete.py:791-793`
- Problem: `messages_dict` modified with memory, but `all_messages` sent to adapter
- Fix: Convert `messages_dict` back to `Message` objects before adapter call

---

## Remaining Work

### P1: Test Failures (7 tests)

**Root Cause Analysis:**

1. **Stream WebSocket tests (6 failures)** - Tests expect first message to be `content`, but getting `connected`
   - `test_stream.py::test_stream_success`
   - `test_stream.py::test_stream_with_parameters`
   - `test_stream.py::test_stream_error_from_provider`
   - `test_stream.py::test_stream_gemini_model`
   - `test_stream_cancel.py::test_backward_compatible_request`
   - `test_stream_cancel.py::test_explicit_request_type`

   **Issue:** Tests not accounting for `connected` message sent before content chunks.
   **Fix:** Update tests to skip `connected` message or check for it first.

2. **Container expiration test (1 failure)** - `test_programmatic.py::test_register_container`
   - Container created with hardcoded past date (2026-01-15) so `is_expired` is True
   - **Fix:** Use dynamic expiration time relative to `now()`

### P2: Lint Violations (18 issues)

Located in:
- `scripts/claude-pty-wrapper.py` - 3 issues (RUF005, SIM105 x2)
- `tests/adapters/test_interface.py` - 2 issues (E721)
- `tests/api/test_complete.py` - 1 issue (SIM117)
- `tests/api/test_stream.py` - 2 issues (SIM117)
- `tests/api/test_stream_cancel.py` - 4 issues (SIM117)
- `tests/core/test_router.py` - 1 issue (B007)
- `tests/core/test_tier_classifier.py` - 1 issue (RUF059)
- `tests/services/test_context_manager.py` - 2 issues (RUF059)

Most are style issues (nested with statements, unused variables). Quick fixes.

### P3: Voice Interruption Cancellation (Architectural)

**Current State:** WebSocket loop awaits completion synchronously. New messages not processed during await.

**Needed:** Redesign with cancellation tokens or async queue with interrupt capability.

**Approach Options:**
1. `asyncio.CancelledError` pattern - Cancel running task on interrupt signal
2. Producer/consumer queue with priority interrupts
3. Timeout-based polling with interrupt flag

**Scope:** This is a larger architectural change. Consider creating dedicated task.

---

## Priority Order

1. **P1 Test Failures** - Quick fixes, unblocks quality gate
2. **P2 Lint Violations** - Mechanical fixes, ~15 min
3. **P3 Voice Interruption** - Create dedicated task for architectural work

---

## Files to Modify

| File | Issue | Fix Type |
|------|-------|----------|
| `tests/api/test_stream.py` | 4 test failures + 2 lint | Update test expectations, combine with statements |
| `tests/api/test_stream_cancel.py` | 2 test failures + 4 lint | Update test expectations, combine with statements |
| `tests/tools/test_programmatic.py` | 1 test failure | Dynamic expiration time |
| `scripts/claude-pty-wrapper.py` | 3 lint | List concat, contextlib.suppress |
| `tests/adapters/test_interface.py` | 2 lint | Use `is` for type comparison |
| `tests/api/test_complete.py` | 1 lint | Combine with statements |
| `tests/core/test_router.py` | 1 lint | Rename unused `i` to `_i` |
| `tests/core/test_tier_classifier.py` | 1 lint | Prefix unused `tier` |
| `tests/services/test_context_manager.py` | 2 lint | Prefix unused `system` |

---

## Resume Instructions

```bash
# Check current state
~/agent-hub/scripts/status.sh
dt --check

# Start with test fixes
cd ~/agent-hub/backend

# Fix stream tests first (update expectations for 'connected' message)
# Then fix container expiration test
# Then fix lint violations
# Finally, create task for voice interruption architectural work
```

## Acceptance Criteria

- [ ] All 7 tests passing
- [ ] All 18 lint violations resolved
- [ ] `dt --check` returns OK
- [ ] Voice interruption task created in SummitFlow (if not fixing this session)

---

## Files Modified Previous Session
- `backend/app/api/complete.py` (memory context bug fix)
- `backend/app/services/memory/context_injector.py` (directive language improvement)
- `backend/app/services/completion.py` (fire-and-forget implementation - verified working)
