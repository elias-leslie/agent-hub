# agent-hub-st

`agent-hub-st` contains the Agent Hub-owned SummitFlow ST commands. Its console
entry point accepts a fixed leading namespace, for example:

```text
agent-hub-st models list --json
```

`st models pull [namespace/]name[:tag]` downloads a public Ollama model through
managed resource admission. The official `ollama` CLI and a running local daemon
are required. A temporary agent-owned loopback registry serves only the frozen
manifest and its referenced blobs; upstream HTTPS redirects stay inside the
helper. Native pull/copy preserves all model metadata, and the command verifies
the installed manifest digest. An existing different destination is refused.
The temporary alias and listener are removed on completion or cancellation.

Defaults are `https://registry.ollama.ai` and `http://127.0.0.1:11434`;
`ST_MODELS_REGISTRY` can select another HTTPS registry origin, and
`ST_MODELS_OLLAMA_HOST` can select a different HTTP port on `127.0.0.1`.
No daemon configuration or inference request is involved. Ollama 0.30.5's
tensor downloader may transfer a blob twice because it follows a local
`Location` header even on a successful streamed response.

`st workflow` drives Agent Hub's durable workflow runner (`/api/workflow-runs`):
create a run from a step plan, `get`/`wait` on it with distinct exit codes,
`add-step`/`revise`/`remove-step` while it runs, `cancel` and `resume`. Aico
sessions fill `launched_by` and `coordinator`. The coordinator guide is the
`st.workflow` usage surface (`st tools manifest --surface st.workflow`).
After a command change, regenerate `st-extensions/workflow.json` with
`describe_app` at `COLUMNS=80`; `tests/test_workflow.py` fails on drift.

## Public helper contract

Version `2`, exposed as `agent_hub_st.PUBLIC_HELPER_API_VERSION`, supports these
integration imports:

- `agent_hub_st.completion`: `call_complete` and its request/payload helpers.
- `agent_hub_st.memory_api`: `agent_hub_request`.
- `agent_hub_st.prompt_api`: `prompt_api`.

Version `2` removed the `feedback_*` helpers and the `feedback` namespace when
Agent Hub retired agent feedback; file actionable issues as SummitFlow tasks.

The package depends only on the public SummitFlow ST SDK and general-purpose
Python libraries. It does not import either product's `app` or `cli` namespace.
