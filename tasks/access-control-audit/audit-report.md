# Agent Hub Access Control Audit - Final Report

**Date:** 2026-01-23
**Status:** In Progress

## Executive Summary

Comprehensive audit of Agent Hub access control system. All production projects now have registered clients. Session attribution bug verified as working. Legacy session cleanup strategy documented.

## Registered Clients

| Client ID | Display Name | Type | Status | Rate Limit |
|-----------|--------------|------|--------|------------|
| 92a11efa-65f9-4a1b-9d6f-b20e9e26ab73 | Consult Skill | service | active | 100 RPM |
| d3689222-69d1-4181-b8ad-f95f66eecde3 | Portfolio AI | service | active | 100 RPM |
| 086e0410-0d54-4572-9775-7ecfb3baf5c4 | SummitFlow | service | active | 100 RPM |
| d7072f90-f6e7-495e-8755-5195d1a66b3e | Agent Hub Dashboard | internal | active | 200 RPM |

### Client Registration Status

- **Consult Skill**: Registered (pre-existing), credentials at `~/.claude/credentials/consult-skill.env`
- **Portfolio AI**: Registered, credentials at `~/.claude/credentials/portfolio-ai.env`
- **SummitFlow**: Registered, credentials at `~/.claude/credentials/summitflow.env`
- **Agent Hub Dashboard**: Registered, credentials at `~/.claude/credentials/agent-hub-dashboard.env`

## Session Attribution

### Current State
- Total sessions: 3,307+
- Sessions with client_id: 4 (authenticated requests to Consult Skill)
- Legacy sessions (client_id IS NULL): 3,303

### Bug Fix Status
The session attribution code was already correct:
1. `AccessControlMiddleware` sets `request.state.client_id = client.id` after authentication
2. `complete.py` extracts via `getattr(http_request.state, "client_id", None)`
3. `_get_or_create_session` accepts `client_id` parameter and saves to session

The 3,303 unauthenticated sessions are legacy data created before access control was implemented.

## Legacy Session Cleanup Strategy

### Recommended Approach
1. Add `is_legacy` boolean column to sessions table
2. Mark all sessions with `client_id IS NULL` as legacy
3. Implement retention policy:
   - Legacy sessions older than 90 days: Archive to cold storage
   - Legacy test project sessions: Eligible for deletion after 30 days
   - Production project legacy sessions: Retain for audit trail

### Test Project Recommendations

| Project | Sessions | Recommendation |
|---------|----------|----------------|
| default | 2,007 | Mark legacy, review for cleanup |
| test | 98 | Delete after 30 days |
| test-llm-comparison | 5 | Delete after 30 days |
| verify | 5 | Delete after 30 days |
| Other test-* projects | 26 | Delete after 30 days |

## max_tokens Review

### Current Configuration
- No artificial limits in agent configs (max_tokens IS NULL for all agents)
- Request max_tokens validated against model output limits
- Model defaults used when max_tokens not specified

### Findings
- Claude Sonnet 4.5: 16,384 output token limit
- Claude Opus 4.5: 32,768 output token limit
- Gemini Pro: 8,192 output token limit
- No issues found with max_tokens handling

## Consult Skill Timeout Diagnosis

### Investigation Results (2026-01-23)

**Finding: Gemini Pro is significantly slower than Gemini Flash**

| Model | Test Prompt | Response Time |
|-------|-------------|---------------|
| gemini-3-flash-preview | "Hi" | ~5-10 seconds |
| gemini-3-pro-preview | "Hi" | >90 seconds (timeout) |

**Root Cause Analysis:**
1. Gemini Pro has much higher latency than Flash
2. No timeout configuration in GeminiAdapter (requests hang indefinitely)
3. First requests after cold start are especially slow

**Recommended Actions:**
1. **Add timeout configuration** to GeminiAdapter (recommend 120s for Pro, 60s for Flash)
2. **Consider using Gemini Flash** for consult skill (faster, still capable)
3. **Implement retry logic** with exponential backoff for timeout failures
4. **Warm up adapters** on service start to avoid cold start delays

### Timeout Configuration Missing (BUG)
The GeminiAdapter in `backend/app/adapters/gemini.py` lacks timeout configuration.
This should be added as a follow-up task.

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| All legitimate projects have registered clients | DONE |
| All access paths authenticated or properly exempt | VERIFIED |
| Legacy sessions marked with cleanup strategy | IN PROGRESS |
| Session attribution bug fixed | VERIFIED (was working) |
| max_tokens handling reviewed | DONE |
| Comprehensive audit report | THIS DOCUMENT |
| Consult skill timeout diagnosed | IN PROGRESS |

## Recommendations

1. **Immediate**: Deploy credentials to production clients
2. **Short-term**: Implement is_legacy migration and cleanup service
3. **Medium-term**: Monitor session attribution for new requests
4. **Long-term**: Implement automated client credential rotation
