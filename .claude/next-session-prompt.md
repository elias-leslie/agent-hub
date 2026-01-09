# Discussion: max_tokens Defaults and Dynamic Adjustment

## Context
Discovered during health check debugging that max_output_tokens defaults are conservative (4096) across the codebase. Modern models support much higher limits.

## Current State

| Endpoint | Default | Max Allowed |
|----------|---------|-------------|
| `/api/complete` | 4096 | 100,000 |
| `/api/stream` | 4096 | 100,000 |
| `/api/orchestration` | 4096 | 128,000 |
| OpenAI compat | None | - |

## Model Capabilities

| Model | Max Output Tokens |
|-------|-------------------|
| Claude 4.5 (all tiers) | 8,192 (16K with beta header) |
| Gemini 3 Flash | 65,536 |
| Gemini 3 Pro | 65,536 |

## Questions to Discuss

1. **Should defaults be higher?** 4096 may truncate agentic outputs (code generation, analysis)

2. **Dynamic adjustment options:**
   - Detect model and set appropriate max?
   - Let user preferences override?
   - Different defaults per use case (chat vs code gen vs analysis)?

3. **Cost implications:** Higher max_tokens = potentially higher cost. But truncated output = wasted tokens + incomplete work.

4. **Streaming consideration:** For streaming, high max_tokens is fine - user can cancel early.

## Files to Change (if adjusting)
- `app/api/complete.py:91` - CompletionRequest default
- `app/api/stream.py:38` - StreamRequest default
- `app/api/orchestration.py:45` - OrchestrationRequest default
- Consider adding to `app/constants.py` for centralization

## Command
```
Continue from .claude/next-session-prompt.md - discuss max_tokens strategy
```
