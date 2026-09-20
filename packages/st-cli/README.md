# agent-hub-st

`agent-hub-st` contains the Agent Hub-owned SummitFlow ST commands. Its console
entry point accepts a fixed leading namespace, for example:

```text
agent-hub-st models list --json
```

## Public helper contract

Version `1`, exposed as `agent_hub_st.PUBLIC_HELPER_API_VERSION`, supports these
integration imports:

- `agent_hub_st.completion`: `call_complete` and its request/payload helpers.
- `agent_hub_st.memory_api`: `agent_hub_request`.
- `agent_hub_st.prompt_api`: `prompt_api`.
- `agent_hub_st.feedback_api`: `feedback_request`.
- `agent_hub_st.feedback_helpers`: feedback paths, constants, and payload builders.
- `agent_hub_st.feedback_commands`: command implementation helpers such as `report_impl`.
- `agent_hub_st.feedback_formatters`: feedback output helpers.

The package depends only on the public SummitFlow ST SDK and general-purpose
Python libraries. It does not import either product's `app` or `cli` namespace.
