# Next Session: Fix SummitFlow Autocode OAuth Block

## The Problem
`st autocode task-xxx` fails with "Usage Policy" error, but identical requests via curl/Python SDK succeed.

## FACTS (Verified)

| Test | Result | Duration | Notes |
|------|--------|----------|-------|
| Direct curl to agent-hub | SUCCESS | 47s | Full prompt works |
| Python AgentHubClient | SUCCESS | ~50s | Full prompt works |
| SummitFlow `st autocode` | FAIL | 3s | Immediate rejection |

**Key observation**: Error response is 309 chars, 3 seconds. Claude rejects IMMEDIATELY. Something in SummitFlow's request triggers instant rejection.

## What Was Fixed (Keep)
- `backend/app/api/complete.py:673-703` - Error responses are NOT cached
- This prevents cache poisoning but doesn't fix root cause

## Root Cause Hypothesis
SummitFlow sends a DIFFERENT request than our tests. The debug hash matched (77800be0) but hash only covers `model + message_count + max_tokens`, NOT the actual message content.

**Most likely difference**: SummitFlow's `agent_hub.py` builds the prompt differently than our test payloads.

## Immediate Action Plan

### Step 1: Capture EXACT SummitFlow request (5 min)
Add debug logging to SummitFlow to dump the exact request:

```python
# summitflow/backend/app/services/agent_hub.py line 275
# Before client.generate(), add:
import json
logger.info(f"AUTOCODE_DEBUG request: {json.dumps({'system': system_prompt[:200], 'prompt': prompt[:200], 'model': self.model})}")
```

### Step 2: Compare to working request (2 min)
Run `st autocode`, capture the debug output, compare to `/tmp/autocode_test.json`.

### Step 3: Find the difference (10 min)
Likely candidates:
- Different model name format
- Different message structure
- Hidden characters in prompt
- Different temperature/max_tokens

### Step 4: Fix the difference (5 min)
Once identified, fix in `agent_hub.py` or `agent_hub_client.py`.

## Files to Check

| File | What to look for |
|------|------------------|
| `summitflow/backend/app/services/agent_hub.py:261-283` | How `_execute_subtask` builds and sends request |
| `summitflow/backend/app/services/agent_hub.py:317-358` | How `_build_execution_prompt` builds user prompt |
| `summitflow/backend/app/services/agent_hub_client.py:214-239` | How `generate()` calls the SDK |
| `agent-hub/packages/agent-hub-client/agent_hub/client.py:146-189` | How SDK sends HTTP request |

## Test Commands

```bash
# Quick test (should fail in 3s, not 60s)
cd ~/summitflow/monkey-fight && timeout 30 st autocode task-4a6927af

# Check logs immediately after
journalctl --user -u agent-hub-backend --since "30 seconds ago" | grep -E "DEBUG|Claude|error"

# Working curl test (for comparison)
curl -s http://localhost:8003/api/complete -H "Content-Type: application/json" -d @/tmp/autocode_test.json | head -c 100
```

## DO NOT
- Run tests with 120s timeouts (error happens in 3s)
- Assume requests are identical without verifying content
- Test the same thing repeatedly
- Skip tracking results

## Success Criteria
- [ ] Identified exact difference between SummitFlow and curl requests
- [ ] Fixed the difference
- [ ] `st autocode task-4a6927af` returns SUCCESS (not Usage Policy error)
