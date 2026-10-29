# @agent-hub/sdk

TypeScript client for Agent Hub: streaming chat turns, sessions, models, agents, live session events and durable
workflow runs. No runtime dependencies. Works in browsers, Electron (main process) and Node 22. It is the one client
shared by the Agent Hub chat page, `@agent-hub/chat-ui` and Aico.

```ts
import { createClient } from '@agent-hub/sdk';

const hub = createClient({
  baseUrl: 'http://localhost:8003', // '' for same-origin in a browser
  clientId: '<registered client id>', // X-Client-Id, X-Request-Source: the backend rejects turns without them
  requestSource: 'aico',
  headers: { 'X-Agent-Hub-Owner-Token': token }, // optional; the SDK never reads token files
  // fetch: myFetch,         // route requests through your own stack (Aico main process)
  // webSocket: myFactory,   // e.g. a `ws` socket
});
```

Errors are `AgentHubError` with `status`, `code` (the server's, e.g. `not_paused`, or `network_error`,
`stream_interrupted`, `lost_contact`), `message` and `details`. Aborts reject with an `AbortError`
(`isAbortError(err)`).

## A chat turn

```ts
const controller = new AbortController();
for await (const event of hub.turns.stream(
  { agent_slug: 'chat', project_id: 'agent-hub', messages: [{ role: 'user', content: 'hi' }] },
  { signal: controller.signal },
)) {
  switch (event.type) {
    case 'connected': console.log('session', event.session_id); break;
    case 'content': process.stdout.write(event.content); break;
    case 'done': console.log(event.model_used, event.fallback_used); break;
    case 'error': console.error(event.error); break;
  }
}
```

Events are a typed union (`connected`, `content`, `thinking`, `tool_use`, `tool_start`, `tool_result`, `turn_retry`,
`context_compacted`, `cancel_acknowledged`, `done`, `error`), deduplicated by `seq`. The iterator ends after the first terminal event
(`done`, `error`, `cancel_acknowledged`). Leaving the loop closes only this client's connection: the server owns the
turn and keeps running it.

To get the finished turn instead, or to drive a UI, use `turns.run(request, { onEvent })`, or fold events yourself
with `createTurnState()` / `applyTurnEvent(state, event)` (it handles `turn_retry` voiding the interrupted model
turn's partial output). `connectRetry: { attempts: 3 }` retries only the connect step (network, 5xx, 429).

## Reattach

A turn keeps running when its client goes away. `turns.stream` reattaches by itself after a dropped connection,
from the last `seq` it saw, with bounded tries (`reattach: { attempts, initialDelayMs, maxDelayMs, jitter }`,
default `DEFAULT_REATTACH`; `reattach: false` turns it off; `onReattach` reports each try). If every try fails it
throws `stream_interrupted` with the last error as `cause`. A refused reattach (404, 409, 410) is thrown at once.

To join a turn yourself, for example from another client or after a restart of the app:

```ts
for await (const event of hub.turns.attach(sessionId, { afterSeq: lastSeq, signal })) {
  if (event.type === 'idle') break; // no turn is running; event.last_state says how the last one ended
}
```

`attach` replays the events after `afterSeq`, follows the turn live and ends at its terminal event. Several clients
see the same stream. A turn cut off by a backend restart ends with `error` code `turn_interrupted`. A session's
`turn_state` (`running` | `idle`) and `turn_phase` come with `sessions.get/list`.

## Cancel

```ts
// Stops the turn on the server after the tool it is running; the stream then ends with cancel_acknowledged.
await hub.turns.cancel(sessionId);
// controller.abort() only drops this client's connection.
```

## A workflow run that waits on the owner

```ts
const run = await hub.workflowRuns.create({
  goal: 'Fix the flaky test',
  project_id: 'agent-hub',
  request_id: 'fix-flaky-1', // idempotent
  steps: [{ key: 'fix', instructions: 'Find and fix it', agent_slug: 'coder' }],
});

// No time limit: only your signal ends the wait. Same outcomes as `st workflow wait`.
const { outcome, run: view, changes } = await hub.workflowRuns.waitFor(run.id, 'needs_owner', {
  signal,
  onChange: (lines) => console.log(lines.join('\n')),
});

if (outcome === 'needs_owner') {
  console.log(view.pause); // e.g. { reason: 'chain_exhausted', step: 'fix', waiting: { fix: { ... } } }
  await hub.workflowRuns.resume(run.id, { action: 'retry', step_key: 'fix', model: 'codex/gpt-6.1-sol' });
  await hub.workflowRuns.waitFor(run.id, 'done', { signal });
}
```

`until` is `'done'` (run completed, failed, cancelled, or needs the owner), `'needs_owner'`, `'any-change'` or
`'step:<key>'`. Outcomes: `completed`, `failed`, `cancelled`, `needs_owner` (any entry in the pause's `waiting` map
counts; a usage-limit wait that clears itself does not), `step_done`, `step_ended`, `changed`.

The rest of the surface: `workflowRuns.list` (filters `launched_by`, `coordinator`), `workflowRuns.get/revise/addSteps/reviseStep/removeStep/cancel/cancelStep`,
`sessions.create/get/list/close/fork/messages/events`, `models.list()`, `agents.list()`, and
`events.subscribe(handler, { sessionIds, eventTypes })` for the owner-only live WebSocket (reconnects by default;
browsers cannot send headers on a WebSocket, so there it relies on same-origin access).

## Types

Request and response types are written by hand in `src/types/`, from the SSE writer and the backend's request models.
Generating them with `openapi-typescript` was not used: the full spec is about 560 KB and the workflow-run
responses are free-form objects in it, so there is nothing to generate for the part that matters most.

## Tests

`tests/` run with the frontend vitest suite (`st check --quick --changed-only`). One opt-in live test runs against a
local Agent Hub: `AGENT_HUB_LIVE=1`, with `AGENT_HUB_URL` (default `http://localhost:8003`) and the client identity
from `AGENT_HUB_CLIENT_ID` / `AGENT_HUB_REQUEST_SOURCE`, or `SUMMITFLOW_CLIENT_ID` / `SUMMITFLOW_REQUEST_SOURCE` in
`~/.env.local` as `st` reads them.
