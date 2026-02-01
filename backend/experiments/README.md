# Experiments

Manual testing scripts for validating SDK capabilities and agentic workflows.

**Not run by CI/CD** - these are for development/experimentation.

## Running Tests

```bash
# From agent-hub/backend directory
source .venv/bin/activate

# Run all experiments
pytest experiments/ -v -s --no-cov

# Run specific test class
pytest experiments/sdk_capabilities_test.py::TestClaudeSessionManagement -v -s --no-cov

# Run benchmarks only
pytest experiments/sdk_capabilities_test.py -k "benchmark" -v -s --no-cov
```

## Files

- `sdk_capabilities_test.py` - Comprehensive Claude/Gemini SDK capability tests
  - Session management (resume, fork, history)
  - Token efficiency measurement
  - Latency benchmarks
  - Thinking modes
  - Tool calling
  - Multimodal support
