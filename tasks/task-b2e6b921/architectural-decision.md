# Architectural Decision: Agent Hub SDK Auth Headers

## Decision Context

- Need to add `client_id`, `client_secret`, `request_source` parameters to both sync and async clients
- Current SDK has ~90% duplication between `AgentHubClient` and `AsyncAgentHubClient`
- OpenAI SDK was NOT implemented (placeholder only) - avoiding unnecessary duplication

## Options Considered

### Option 1: unasync Code Generation
Write async once, generate sync automatically.

**Pros:**
- Single source of truth for implementation
- Zero duplication

**Cons:**
- Adds build-time code generation complexity
- Requires additional tooling in CI/CD
- Makes code harder to debug (generated code in build artifacts)
- Anthropic SDK doesn't use this approach despite similar duplication

### Option 2: Shared Base Class (CHOSEN)
Extract common logic to `BaseAgentHubClient`, keep sync/async separate for IO.

**Pros:**
- Follows Anthropic SDK pattern (`BaseClient[_HttpxClientT, _DefaultStreamT]`)
- Minimal refactoring - extract common logic, preserve existing API
- Easy to maintain - clear separation between state management and IO operations
- No breaking changes to client instantiation
- Easier to debug - all code is directly readable

**Cons:**
- Some duplication remains in IO method signatures (complete, stream, etc.)
- Need to keep sync/async methods in sync manually

## Decision

**Chosen: Shared Base Class Pattern**

Implementation:
1. Create `BaseAgentHubClient` with:
   - All `__init__` logic (base_url, timeout, client_name, auto_inject_headers, + NEW: client_id, client_secret, request_source)
   - Auth header construction (api_key + credential headers)
   - Kill switch/dormant mode state management
   - Helper methods (_inject_source_path, _check_disabled, etc.)
   
2. Update `AgentHubClient` and `AsyncAgentHubClient` to:
   - Inherit from `BaseAgentHubClient`
   - Keep only IO-specific logic (_get_client, complete, stream, sessions methods)
   - Call parent's `_build_auth_headers()` when constructing httpx clients

3. Auth header injection:
   ```python
   def _build_auth_headers(self) -> dict[str, str]:
       """Build authentication headers."""
       headers = {}
       if self.api_key:
           headers["Authorization"] = f"Bearer {self.api_key}"
       if self.client_id:
           headers["X-Client-Id"] = self.client_id
       if self.client_secret:
           headers["X-Client-Secret"] = self.client_secret
       if self.request_source:
           headers["X-Request-Source"] = self.request_source
       return headers
   ```

## References

- Anthropic SDK: `/home/kasadis/agent-hub/backend/.venv/lib/python3.13/site-packages/anthropic/_base_client.py`
  - Lines 367-417: `BaseClient` generic class
  - Lines 674-686: `auth_headers` property pattern
  - Lines 907-1544: `SyncAPIClient` and `AsyncAPIClient` inheritance
  
- Current agent-hub SDK: `/home/kasadis/agent-hub/packages/agent-hub-client/agent_hub/client.py`
  - Lines 96-586: `AgentHubClient` (sync)
  - Lines 587+: `AsyncAgentHubClient` (async)
  - Lines 174-190: `_get_client()` with header construction (sync)

## Impact

- **Backend SDK**: Refactor to shared base class + add credential parameters
- **SummitFlow**: No changes needed to client usage (backward compatible)
- **Portfolio-AI**: No changes needed to client usage  
- **Passport**: No changes needed to client usage
- **Tests**: Add tests for credential header injection and backward compatibility
