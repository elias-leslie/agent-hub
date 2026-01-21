# Test Adapter Mocking Audit

## Problem Statement

Tests across our projects are making **real LLM API calls** instead of properly mocking adapters. This causes:
- Real sessions appearing in Agent Hub `/sessions` dashboard
- Actual token consumption and costs
- Flaky tests dependent on external API availability
- Slow test execution

The kill switch with `X-Source-Client: pytest` header was added to track/block test traffic, but blocking causes tests to fail with 403. The root cause is tests not properly mocking LLM adapters.

## Objective

Audit and fix ALL tests across ALL projects to ensure:
1. No test makes real LLM API calls (Anthropic, Google, OpenAI)
2. No test creates real database sessions in Agent Hub
3. All adapter interactions are properly mocked
4. Tests pass regardless of kill switch state
5. Tests pass without network connectivity

## Projects to Audit

| Project | Test Location | LLM Integration |
|---------|---------------|-----------------|
| agent-hub | `~/agent-hub/backend/tests/` | Direct adapter calls (ClaudeAdapter, GeminiAdapter, GeminiImageAdapter) |
| summitflow | `~/summitflow/backend/tests/` | AgentHubClient calls to agent-hub API |
| portfolio-ai | `~/portfolio-ai/backend/tests/` | AgentHubClient or direct API calls |
| terminal | `~/terminal/terminal/tests/` | May have LLM integration |
| monkey-fight | `~/monkey-fight/backend/tests/` | May use agent-hub for AI features |

## Audit Methodology

### Step 1: Find All Test Files
```bash
# For each project
find ~/agent-hub/backend/tests -name "test_*.py" -type f
find ~/summitflow/backend/tests -name "test_*.py" -type f
find ~/portfolio-ai/backend/tests -name "test_*.py" -type f
find ~/terminal -name "test_*.py" -type f
find ~/monkey-fight -name "test_*.py" -type f 2>/dev/null
```

### Step 2: Identify Problematic Patterns

Search for tests that:

1. **Import adapters without mocking:**
```python
# BAD - imports real adapter
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter

# GOOD - uses mock
from unittest.mock import AsyncMock, patch
```

2. **Call completion endpoints without mocking:**
```python
# BAD - real API call
response = client.post("/api/complete", json={...})

# GOOD - mocked adapter
with patch("app.api.complete.get_adapter") as mock:
    mock.return_value.complete = AsyncMock(return_value=fake_result)
    response = client.post("/api/complete", json={...})
```

3. **Use AgentHubClient without mocking:**
```python
# BAD - real HTTP call to agent-hub
from app.services.agent_hub_client import AgentHubClient
client = AgentHubClient()
result = await client.complete(...)

# GOOD - mocked client
with patch("app.services.agent_hub_client.AgentHubClient") as mock:
    mock.return_value.complete = AsyncMock(return_value=fake_result)
```

4. **Create TestClient without adapter mocks:**
```python
# BAD - real adapters will be used
client = TestClient(app)
response = client.post("/api/complete", ...)

# GOOD - adapter mocked before request
with patch("app.api.complete.ClaudeAdapter") as mock:
    mock.return_value.complete = AsyncMock(return_value=CompletionResult(...))
    response = client.post("/api/complete", ...)
```

### Step 3: Grep Commands to Find Issues

```bash
# Find tests that import adapters
rg "from app.adapters" ~/agent-hub/backend/tests --type py

# Find tests calling /api/complete without obvious mocking
rg -l "post.*complete" ~/agent-hub/backend/tests --type py

# Find tests using AgentHubClient
rg "AgentHubClient" ~/summitflow/backend/tests --type py
rg "AgentHubClient" ~/portfolio-ai/backend/tests --type py

# Find tests that don't mock but call LLM-related endpoints
rg -l "(complete|generate|chat)" ~/*/backend/tests --type py | xargs rg -L "mock|patch|Mock"
```

### Step 4: Fix Pattern

For each problematic test:

1. **Identify what needs mocking:**
   - Adapter class (ClaudeAdapter, GeminiAdapter)
   - Adapter method (complete, stream, generate_image)
   - HTTP client for external calls

2. **Create appropriate mock:**
```python
from unittest.mock import AsyncMock, patch, MagicMock
from app.adapters.base import CompletionResult, FinishReason

@pytest.fixture
def mock_claude_adapter():
    """Mock ClaudeAdapter to prevent real API calls."""
    with patch("app.api.complete.ClaudeAdapter") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.complete = AsyncMock(return_value=CompletionResult(
            content="Mocked response",
            model="claude-sonnet-4-5",
            usage={"input_tokens": 10, "output_tokens": 20},
            finish_reason=FinishReason.STOP,
        ))
        mock_cls.return_value = mock_instance
        yield mock_instance
```

3. **Use the mock in test:**
```python
def test_complete_endpoint(client, mock_claude_adapter):
    response = client.post("/api/complete", json={...})
    assert response.status_code == 200
    mock_claude_adapter.complete.assert_called_once()
```

### Step 5: Verification

After fixes, verify no real calls are made:

1. **Run tests with network disabled:**
```bash
# Linux - block outbound HTTPS
sudo iptables -A OUTPUT -p tcp --dport 443 -j DROP
pytest tests/
sudo iptables -D OUTPUT -p tcp --dport 443 -j DROP
```

2. **Check no new sessions created:**
```bash
# Before tests
curl -s http://localhost:8003/api/sessions | jq '.total'
# Run tests
pytest tests/
# After tests - count should be same
curl -s http://localhost:8003/api/sessions | jq '.total'
```

3. **Block pytest client and verify tests pass:**
```bash
# In Admin UI, disable 'pytest' client
pytest tests/
# All tests should still pass (no real calls = no 403s)
```

## Acceptance Criteria

- [ ] All tests pass with `pytest` client blocked in Admin UI
- [ ] All tests pass with network disabled (no external API access)
- [ ] No new sessions appear in agent-hub `/sessions` during test runs
- [ ] Zero real token usage during test execution
- [ ] Each adapter class has a corresponding pytest fixture for mocking
- [ ] Documented patterns in each project's `tests/conftest.py`

## Common Mock Fixtures to Create

### agent-hub/backend/tests/conftest.py
```python
@pytest.fixture
def mock_claude_adapter():
    """Mock ClaudeAdapter for all tests."""
    ...

@pytest.fixture
def mock_gemini_adapter():
    """Mock GeminiAdapter for all tests."""
    ...

@pytest.fixture
def mock_all_adapters(mock_claude_adapter, mock_gemini_adapter):
    """Convenience fixture to mock all LLM adapters."""
    return {"claude": mock_claude_adapter, "gemini": mock_gemini_adapter}
```

### summitflow/backend/tests/conftest.py
```python
@pytest.fixture
def mock_agent_hub_client():
    """Mock AgentHubClient to prevent real API calls."""
    ...
```

## Priority Order

1. **agent-hub** - Source of LLM calls, fix adapters first
2. **summitflow** - Heavy AgentHubClient usage
3. **portfolio-ai** - AI-powered features
4. **terminal** - Check for any LLM usage
5. **monkey-fight** - Game AI features

## Notes

- Some integration tests may legitimately need real calls - mark with `@pytest.mark.integration` and skip by default
- The `--run-integration` flag should be required for tests that need real APIs
- Consider adding CI check that fails if tests make real API calls
