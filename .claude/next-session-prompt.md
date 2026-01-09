# Task: Output Limit Visibility & Truncation Detection

## Context
Previous session implemented model-aware max_tokens defaults (commit a14e5f3). Added:
- `OUTPUT_LIMITS` dict in `app/constants.py` with per-model limits
- `get_output_limit(model)` and `get_recommended_max_tokens(model, use_case)` in `token_counter.py`
- Updated defaults: 8192 general, 4096 chat, 64000 agentic

**Problem:** Limits are set but violations are invisible. When output truncates, users don't know.

## What's Needed

### 1. Input Validation (Backend)
- Validate `max_tokens` against `get_output_limit(model)` 
- Options: reject with 400, cap silently with warning header, or allow with warning in response
- Location: `app/api/complete.py`, `app/api/stream.py`

### 2. Response Enrichment
Add `output_usage` to response (similar to existing `context_usage`):
```python
class OutputUsage(BaseModel):
    output_tokens: int          # Actual tokens generated
    max_tokens_requested: int   # What user asked for
    model_limit: int            # Model's max capability
    was_truncated: bool         # True if finish_reason="max_tokens"
    warning: str | None         # "Response truncated" or "Requested max_tokens exceeds model limit"
```

### 3. Truncation Detection
- Check `finish_reason == "max_tokens"` 
- Set `was_truncated=True` and populate warning
- Log truncation event for telemetry

### 4. Frontend Visibility
- `frontend/src/hooks/use-chat-stream.ts` - detect truncation in stream done event
- Add toast/alert: "Response was truncated at X tokens. Full response may be incomplete."
- Visual indicator on truncated messages

### 5. Telemetry & Dashboard
- Track truncation events: model, endpoint, requested vs actual tokens
- Store in database for dashboard queries
- Add dashboard widget showing:
  - Truncation rate over time (line chart)
  - Truncations by model (bar chart)
  - Recent truncation events (table)
- Alert threshold configuration

## UI/UX Requirements
**IMPORTANT:** Use `/frontend-design` skill for ALL UI components. This includes:
- Truncation warning toast/banner
- Truncated message indicator (icon/badge on affected messages)
- Dashboard truncation metrics widgets
- Any settings UI for alert thresholds

The frontend-design skill ensures polished, production-grade components that avoid generic AI aesthetics.

## Files to Modify
- `backend/app/api/complete.py` - validation + response enrichment
- `backend/app/api/stream.py` - validation + truncation in events
- `backend/app/services/token_counter.py` - add validation helper
- `backend/app/models.py` - truncation event model for telemetry
- `backend/app/api/dashboard.py` - truncation metrics endpoint
- `frontend/src/hooks/use-chat-stream.ts` - truncation detection
- `frontend/src/components/` - use /frontend-design for all new components

## Command
```
Continue from .claude/next-session-prompt.md - implement output limit visibility
```
