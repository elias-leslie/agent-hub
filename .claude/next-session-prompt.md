# Output Limit Visibility - Verification Session

## Quick Test Commands

### 1. Backend Truncation Test (Gemini - respects max_tokens)
```bash
curl -s -X POST http://localhost:8003/api/complete \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"Count from 1 to 1000, each number on a new line"}],"max_tokens":50,"persist_session":true,"project_id":"test"}' | jq '{truncated: .output_usage.was_truncated, warning: .output_usage.warning, tokens: "\(.output_usage.output_tokens)/\(.output_usage.max_tokens_requested)"}'
```

Expected output:
```json
{
  "truncated": true,
  "warning": "Response truncated at 50 tokens (max_tokens limit reached).",
  "tokens": "50/50"
}
```

### 2. Analytics Endpoint
```bash
curl -s "http://localhost:8003/api/analytics/truncations?days=7" | jq '{total: .total_truncations, rate: "\(.truncation_rate | . * 100 | floor / 100)%", by_model: [.aggregations[] | {model: .group_key, count: .truncation_count}]}'
```

### 3. Frontend UI Test
1. Open http://localhost:3003
2. In chat, send: "Count from 1 to 1000, each number on its own line"
3. The response should show the **TruncationIndicator** gauge if truncated
4. Click the indicator to expand details (Output, Requested, Model Max)

## Cloudflare Production Test

### 1. Backend Test (with CF auth)
```bash
source ~/.cloudflare-access
curl -s -X POST https://api.summitflow.dev/api/complete \
  -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"Write numbers 1-500"}],"max_tokens":50}' | jq '.output_usage'
```

### 2. Analytics Endpoint (CF)
```bash
source ~/.cloudflare-access
curl -s "https://api.summitflow.dev/api/analytics/truncations?days=7" \
  -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" | jq '.'
```

## What Was Implemented

### Backend
- `token_counter.py`: `OutputUsage`, `MaxTokensValidation`, `validate_max_tokens()`, `build_output_usage()`
- `models.py`: `TruncationEvent` table for telemetry
- `complete.py`: Validates max_tokens, builds output_usage, logs truncation events
- `stream.py`: Same for WebSocket streaming
- `analytics.py`: `GET /api/analytics/truncations` endpoint

### Frontend
- `truncation-indicator.tsx`: Visual gauge component with expandable details
- `use-truncation-toast.ts`: Auto-toast hook for truncation notifications
- `truncation-metrics.tsx`: Dashboard widget for analytics
- `message-list.tsx`: Integrated TruncationIndicator component

## Known Limitation
Claude OAuth via Agent SDK does NOT enforce max_tokens - the model generates full responses. Truncation detection still works (reports false) but won't actually truncate. Use Gemini or Claude API key mode to test actual truncation.

## Files Changed
```
backend/app/services/token_counter.py    # OutputUsage, validation
backend/app/models.py                     # TruncationEvent model
backend/app/api/complete.py              # output_usage in response
backend/app/api/stream.py                # output_usage in stream done
backend/app/api/analytics.py             # /truncations endpoint
backend/migrations/versions/27229f433f34_add_truncation_events_table.py

frontend/src/types/chat.ts               # truncated, maxTokensRequested, etc.
frontend/src/hooks/use-chat-stream.ts    # Populate truncation fields
frontend/src/hooks/use-truncation-toast.ts  # Auto-toast hook
frontend/src/components/chat/truncation-indicator.tsx  # Gauge UI
frontend/src/components/chat/message-list.tsx  # Uses TruncationIndicator
frontend/src/components/analytics/truncation-metrics.tsx  # Dashboard widget
```

## Verification Checklist
- [ ] Backend: `output_usage.was_truncated` is true when finish_reason contains "max_tokens"
- [ ] Backend: Warning message generated for truncated responses
- [ ] Backend: TruncationEvent logged to database (when persist_session=true)
- [ ] Backend: Analytics endpoint returns truncation metrics
- [ ] Frontend: TruncationIndicator shows gauge with token counts
- [ ] Frontend: Expandable details panel works
- [ ] Frontend: Toast notification appears on truncation (if useTruncationToast hook integrated)
- [ ] Cloudflare: Same tests pass on production URLs
