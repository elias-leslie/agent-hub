# Agent Hub Access Control Audit - Initial Findings

**Date:** 2026-01-23

## Executive Summary

Initial audit of Agent Hub access control reveals significant gaps in authentication coverage:
- 3,303 sessions have no client attribution (`client_id IS NULL`)
- Only 1 registered client (Consult Skill)
- Production projects (Portfolio AI, SummitFlow) have no registered clients

## Session Statistics by Project

| Project | Total Sessions | Authenticated | Auth Rate |
|---------|----------------|---------------|-----------|
| default | 2,007 | 0 | 0% |
| portfolio-ai | 745 | 0 | 0% |
| claude-consultation | 300 | 3 | 1% |
| summitflow | 109 | 0 | 0% |
| test | 98 | 1 | 1% |
| agent-hub | 9 | 0 | 0% |
| test-llm-comparison | 5 | 0 | 0% |
| verify | 5 | 0 | 0% |
| Other test projects | 26 | 0 | 0% |

**Total:** 3,307 sessions, 4 authenticated (0.1% auth rate)

## Registered Clients

| Client ID | Display Name | Type | Status |
|-----------|--------------|------|--------|
| 92a11efa-65f9-4a1b-9d6f-b20e9e26ab73 | Consult Skill | service | active |

## Key Findings

### 1. Legacy Sessions (HIGH PRIORITY)
- 3,303 sessions created before access control implementation
- No way to attribute these to specific clients retroactively
- Need cleanup strategy and migration path

### 2. Missing Client Registrations (HIGH PRIORITY)
- **Portfolio AI**: 745 sessions, no client
- **SummitFlow**: 109 sessions, no client
- **Agent Hub Dashboard**: No client registered

### 3. Bug: Session Attribution Not Working
- `session.client_id` is not being set even for authenticated requests
- AccessControlMiddleware sets `request.state.client_id`
- But `_get_or_create_session` doesn't read from `request.state`

### 4. Test/Ephemeral Projects
- 25+ test project IDs with few sessions each
- Should implement cleanup policy for test data

## Recommendations

1. **Register clients** for all production projects (Portfolio AI, SummitFlow, Dashboard)
2. **Fix session attribution bug** - pass client_id from middleware to session creation
3. **Mark legacy sessions** - add `is_legacy` column, mark all NULL client_id sessions
4. **Implement cleanup** - scheduled job to archive/delete old test sessions
5. **Review max_tokens** - ensure no artificial limits blocking production usage

## Next Steps

1. Subtask 1.2: Fix session attribution bug
2. Subtask 2.1: Register production clients
3. Subtask 2.2: Mark and cleanup legacy sessions
