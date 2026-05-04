# Agent Hub Persona Tool Surface Contract

Canonical owner: `backend/app/services/tools/persona_tool_surface.py`.

## Layers

- Provider-native Claude built-ins stay in `backend/app/adapters/_claude_constants.py`: `Read`, `Write`, `Bash`, `Edit`.
- Persona hot-loaded runtime tools are owned only by `persona_tool_surface.py`.
- Wrapper CLIs such as `st`, `db`, `web-research`, and `rebuild.sh` are bash workflows. They are prompt guidance only when `Bash` is available, not separate runtime authority.

## Persona Runtime Tools

| Tier | Hot-loaded tool ids |
| --- | --- |
| `off` | none |
| `read` | `read_file` |
| `write` | `read_file`, `write_file` |
| `yolo` | `bash`, `read_file`, `write_file` |

## Operator Display

| Tier | Operator names |
| --- | --- |
| `off` | none |
| `read` | `Read` |
| `write` | `Read`, `Write`, `Edit` |
| `yolo` | `Read`, `Write`, `Edit`, `Bash` |

Unknown or missing tiers fail closed to `off`.

## Change Rule

Future persona surface changes must update the owner module, provisioning, permission/previews, this doc, and regression tests together. Do not add persona convenience tools to the operator surface through the shared registry or deferred catalog.
