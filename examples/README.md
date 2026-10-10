# Agent Hub Examples

Every caller uses the `agent-hub-client` SDK (`packages/agent-hub-client`); there
is no supported raw-HTTP client path. More SDK examples (basic completion,
streaming, sessions) live in `packages/agent-hub-client/examples/`.

## Setup

```bash
# The backend runs as a managed service: st service status agent-hub
pip install -e packages/agent-hub-client
```

## Examples

| File | Description |
|------|-------------|
| `sdk_example.py` | SDK features: completion, streaming, sessions, vision |

Callers identify themselves with `client_id` and `request_source` (ST tools load
them with `st_sdk.credentials.load_credentials()`), and route by `agent_slug`.
