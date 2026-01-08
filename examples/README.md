# Agent Hub Examples

Example scripts demonstrating Agent Hub features.

## Setup

```bash
# Ensure backend is running
cd ~/agent-hub/backend
uvicorn app.main:app --port 8003

# Install SDK (for sdk_example.py)
pip install -e packages/agent-hub-client
```

## Examples

| File | Description |
|------|-------------|
| `simple_completion.py` | Basic completion request with httpx |
| `streaming_example.py` | SSE streaming responses |
| `session_management.py` | Multi-turn conversations with sessions |
| `orchestration_example.py` | Multi-agent queries with tracing |
| `sdk_example.py` | Full SDK features: completion, streaming, sessions, vision |

## Running

```bash
# Simple completion
python examples/simple_completion.py

# Streaming
python examples/streaming_example.py

# Sessions
python examples/session_management.py

# SDK
python examples/sdk_example.py
```

## Requirements

- httpx (`pip install httpx`)
- agent-hub-client (`pip install -e packages/agent-hub-client`)
- Running Agent Hub backend at localhost:8003
