# Security Policy

## Reporting a Vulnerability

Please report suspected vulnerabilities using
[GitHub's private vulnerability reporting](https://github.com/elias-leslie/agent-hub/security/advisories/new).

Include:

- affected component or endpoint
- reproduction steps or proof of concept
- expected impact
- any known workaround or mitigation

Do not open a public GitHub issue for a suspected security problem.

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest `main` | Yes |
| older commits and snapshots | No |

## Response Expectations

Security reports are handled on a best-effort basis. No formal SLA is offered.

## Voice WebSocket trust boundary

`/api/voice/ws` currently identifies a caller with its `user_id` query parameter;
it does not cryptographically authenticate that identity. Keep the endpoint on
loopback or behind an authenticated, trusted reverse proxy. Do not expose it
directly to an untrusted network.

The server applies resource backstops independently of caller honesty: one
active recording per claimed identity, a host-capacity-derived global recording
ceiling, and one 30-second / 960,000-byte mono 16-kHz PCM buffer per recording.
Recording ownership and buffers are released on stop, limit violations,
disconnects, receive errors, and handler cancellation. Transcript contents are
returned to the caller but are not written to server logs.
