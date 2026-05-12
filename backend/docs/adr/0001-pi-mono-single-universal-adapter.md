# ADR 0001: Pi-Mono Single Universal Adapter

## Status

Accepted — 2026-05-12.

## Context

`backend/tasks/agent-framework-convergence/convergence-map.md` and
`backend/tasks/agent-framework-convergence/pi-mono-catalog.md` define the
target: Agent Hub's text LLM runtime follows pi-mono's universal adapter shape.
The old text adapter tree exposed provider-specific `complete`, `stream`,
health, tool-loop, and runtime-session surfaces. That made provider behavior
fragmented and kept duplicate result and tool-loop types alive.

The downstream HTTP and SSE contract in `downstream-consumers.md` remains the
boundary. Internals can converge; route names, response fields, and all 9 SSE
event names stay stable.

## Decision

Agent Hub text completion uses one pi-mono-shaped surface:

- `app.llm.types` owns universal `Message`, `AssistantMessage`, `Usage`,
  `StopReason`, `Context`, `Tool`, `Model`, and the 12-variant
  `AssistantMessageEvent`.
- `app.llm.api_registry.ApiProvider` has exactly `stream` and `stream_simple`.
- `app.llm.stream.complete*` remains a thin `stream().result()` wrapper.
- Provider modules register through `register_api_provider`; outside callers use
  `api_registry.get_api_provider()`.
- The adapter emits tool calls; Agent Hub's service layer executes tools and
  feeds back `ToolResultMessage`.

## D1-D10 Summary

D1 creates `backend/app/llm/`. D2 locks internal stop reasons to pi-mono's five
values. D3 keeps provider health outside `ApiProvider`. D4 collapses Cloudflare
text models into OpenAI-compatible catalog entries. D5 carries container state on
tool-result details. D6 deletes adapter-owned tool-event/session APIs. D7
collapses Codex/Claude onto one Anthropic provider plus OAuth differences. D8
adds import-linter and AST guardrails. D9 keeps memory/citations out of adapter
types. D10 preserves pi-mono vocabulary and file naming in Python form.

## Outcome

Current converged surface:

- `backend/app/llm/`: 28 Python files, 6,833 LOC.
- `backend/app/api/complete/`: 39 Python files, 7,313 LOC.
- Combined: 67 Python files, 14,146 LOC.

The summary target was approximately 38 files / 8,300 LOC. The remaining gap is
intentional residue documented in Phase 4D wave 3: live HTTP helpers
(`complete_orchestrator`, `orchestration_helpers`, `handlers`,
`handler_helpers`, `async_dispatch`, `execution`, `complete_execution`,
`event_helpers`, `helpers`, `work_context`) still sit on the downstream contract
path and were not deleted as theatre.

## Consequences

The adapter boundary is small enough to guard mechanically. New text providers
must register once under `app.llm.providers`; they cannot introduce a parallel
result shape or direct imports from application layers. Future collapse work can
target HTTP helper count without reopening provider semantics.

