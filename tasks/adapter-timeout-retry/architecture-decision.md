# Architecture Decision: Adapter Timeout and Retry

## Context

The Claude and Gemini adapters needed timeout and retry mechanisms to handle transient failures and prevent indefinite hangs.

## Decisions

### 1. Claude Adapter: OAuth-Only Mode

**Decision**: Remove all API key code from Claude adapter (~400 lines).

**Rationale**: API key mode was not being used. OAuth via Claude CLI provides zero API cost and is the preferred approach.

**Impact**: ~500 lines removed, simpler codebase, single authentication path.

### 2. Claude OAuth: Application-Level Timeout (120 seconds)

**Decision**: Use `asyncio.wait_for(timeout=120.0)` to wrap OAuth calls.

**Rationale**:
- ClaudeAgentOptions has NO timeout parameter - the CLI controls timeouts internally
- Application-level timeout is NOT true idle detection but prevents indefinite hangs
- 120s chosen based on profiling (max observed: 76s with extended thinking)

**Implementation**:
```python
await asyncio.wait_for(client.query(full_prompt), timeout=120.0)
```

### 3. Gemini SDK: Transport-Level Timeout (90 seconds)

**Decision**: Use `HttpOptions(timeout=90)` for TRUE idle detection at transport layer.

**Rationale**:
- SDK supports native timeout via HttpOptions
- Detects when no bytes flow on the socket (stalled connection)
- 90s chosen based on profiling: max observed 51s + 25s extended thinking buffer = 76s, rounded up

**Implementation**:
```python
self._client = genai.Client(
    api_key=self._api_key,
    http_options=HttpOptions(timeout=90),
)
```

### 4. Retry Logic: tenacity with Exponential Backoff

**Decision**: Use tenacity library with `@with_retry` decorator.

**Rationale**:
- Proven pattern from graphiti reference
- Handles transient errors (503, 429, 5xx)
- Exponential backoff prevents thundering herd

**Configuration**:
- `stop_after_attempt(3)` - max 3 retries
- `wait_random_exponential(min=2, max=30)` - 2-30 second waits with jitter

**Retriable Errors**:
- HTTP 429 (rate limit)
- HTTP 503 (service unavailable)
- HTTP 5xx (server errors)
- `ProviderError` with `retriable=True`

## Testing

- Unit tests for `is_retriable_error` function
- Integration tests for retry behavior (transient vs permanent errors)
- Timeout tests verifying correct exception handling

## References

- Profiling data from production usage
- graphiti retry patterns
- Google GenAI SDK documentation for HttpOptions
