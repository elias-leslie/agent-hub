/**
 * SSE fixtures for the turn stream.
 *
 * `recordedPong` was recorded from a live `POST /api/complete` (agent `provider-liveness-probe`, prompt "Reply with
 * exactly: pong") on 2026-10-28 and trimmed to its first thinking deltas and its end (`seq` gaps are as sent).
 * The others are written to the same wire format (`backend/app/api/complete/sse_writer.py`) for paths that are
 * awkward to record on demand: tool calls, a turn retry, an error and a cancel.
 */

export const recordedPong = "data: {\"type\": \"connected\", \"seq\": 1, \"session_id\": \"45f6f61d-0e1c-4549-8997-8d3ba613e701\", \"model\": \"nvidia/nemotron-3.5-lightning-30b-a3b\", \"provider\": \"nvidia\"}\n\ndata: {\"type\": \"thinking\", \"seq\": 2, \"content\": \"The\"}\n\ndata: {\"type\": \"thinking\", \"seq\": 3, \"content\": \" user\"}\n\ndata: {\"type\": \"thinking\", \"seq\": 4, \"content\": \" is\"}\n\ndata: {\"type\": \"thinking\", \"seq\": 5, \"content\": \" asking\"}\n\ndata: {\"type\": \"thinking\", \"seq\": 6, \"content\": \" me\"}\n\ndata: {\"type\": \"content\", \"seq\": 145, \"content\": \"p\", \"model\": \"nvidia/nemotron-3.5-lightning-30b-a3b\", \"provider\": \"nvidia\", \"agent_used\": \"provider-liveness-probe\", \"fallback_used\": false}\n\ndata: {\"type\": \"content\", \"seq\": 146, \"content\": \"ong\", \"model\": \"nvidia/nemotron-3.5-lightning-30b-a3b\", \"provider\": \"nvidia\", \"agent_used\": \"provider-liveness-probe\", \"fallback_used\": false}\n\ndata: {\"type\": \"done\", \"seq\": 147, \"model\": \"nvidia/nemotron-3.5-lightning-30b-a3b\", \"provider\": \"nvidia\", \"agent_used\": \"provider-liveness-probe\", \"fallback_used\": false, \"cost_usd\": 0.0, \"finish_reason\": \"stop\", \"input_tokens\": 2830, \"output_tokens\": 147, \"model_used\": \"nvidia/nemotron-3.5-lightning-30b-a3b\", \"session_id\": \"45f6f61d-0e1c-4549-8997-8d3ba613e701\", \"model_display_name\": \"Nemotron 3.5 Lightning 30B-A3B (NVIDIA)\"}\n\ndata: [DONE]\n\n";

/** One `data:` event as the backend writes it. */
export function sse(payload: unknown): string {
    return `data: ${JSON.stringify(payload)}\n\n`;
}

const routing = {
    model: 'm/primary',
    provider: 'p',
    agent_used: 'chat',
    fallback_used: false,
};

/** A turn that calls one tool, then answers. */
export const toolTurn = [
    sse({ type: 'connected', seq: 1, session_id: 's-tool', model: 'm/primary', provider: 'p' }),
    sse({ type: 'content', seq: 2, content: 'Let me look. ', ...routing }),
    sse({ type: 'tool_use', seq: 3, tool_id: 't1', tool_name: 'read_file', tool_input: { path: 'a.txt' } }),
    sse({ type: 'tool_start', seq: 4, tool_id: 't1', tool_name: 'read_file' }),
    sse({ type: 'tool_result', seq: 5, tool_id: 't1', tool_result: 'hello', tool_status: 'complete' }),
    sse({ type: 'content', seq: 6, content: 'It says hello.', ...routing }),
    sse({ type: 'done', seq: 7, session_id: 's-tool', input_tokens: 10, output_tokens: 5, ...routing }),
    'data: [DONE]\n\n',
].join('');

/** The second model turn is interrupted after tool output and re-run: its partial text is void. */
export const retryTurn = [
    sse({ type: 'connected', seq: 1, session_id: 's-retry' }),
    sse({ type: 'content', seq: 2, content: 'First turn. ', ...routing }),
    sse({ type: 'tool_use', seq: 3, tool_id: 't1', tool_name: 'ls', tool_input: {} }),
    sse({ type: 'tool_result', seq: 4, tool_id: 't1', tool_result: 'a b', tool_status: 'complete' }),
    sse({ type: 'content', seq: 5, content: 'partial that will be dr', ...routing }),
    sse({ type: 'thinking', seq: 6, content: 'half a thought' }),
    sse({ type: 'turn_retry', seq: 7, attempt: 1, max_retries: 3, reason: 'stream interrupted' }),
    sse({ type: 'content', seq: 8, content: 'Second try.', ...routing }),
    sse({ type: 'done', seq: 9, session_id: 's-retry', ...routing }),
    'data: [DONE]\n\n',
].join('');

/** The history is summarized before the second model call; the answer text is untouched. */
export const compactedTurn = [
    sse({ type: 'connected', seq: 1, session_id: 's-compact' }),
    sse({ type: 'content', seq: 2, content: 'Reading. ', ...routing }),
    sse({ type: 'context_compacted', seq: 3, status: 'ok', tokens_before: 9200, tokens_after: 6400, summarizer_model: 'm/small', messages_summarized: 12, messages_kept: 4, cost_usd: 0.002 }),
    sse({ type: 'content', seq: 4, content: 'Done.', ...routing }),
    sse({ type: 'done', seq: 5, session_id: 's-compact', ...routing }),
    'data: [DONE]\n\n',
].join('');

export const errorTurn = [
    sse({ type: 'connected', seq: 1, session_id: 's-err' }),
    sse({ type: 'content', seq: 2, content: 'Partial', ...routing }),
    sse({ type: 'error', seq: 3, error: 'Rate limit exceeded', model: 'm/primary', provider: 'p', session_id: 's-err' }),
    'data: [DONE]\n\n',
].join('');

export const cancelTurn = [
    sse({ type: 'connected', seq: 1, session_id: 's-cancel' }),
    sse({ type: 'content', seq: 2, content: 'Working on', ...routing }),
    sse({ type: 'cancel_acknowledged', seq: 3, session_id: 's-cancel' }),
].join('');

/**
 * A server-owned turn as the backend sends it (`connected` carries `turn_id`), cut into the part a first connection
 * delivered and the rest a reattach replays. Written to the wire format of `backend/app/services/turn_runs.py`.
 */
export const ownedTurn = {
    sessionId: 's-owned',
    turnId: 'turn-1',
    events: [
        { type: 'connected', seq: 1, session_id: 's-owned', turn_id: 'turn-1', model: 'm/primary', provider: 'p' },
        { type: 'content', seq: 2, content: 'One ', ...routing },
        { type: 'content', seq: 3, content: 'two ', ...routing },
        { type: 'tool_use', seq: 4, tool_id: 't1', tool_name: 'ls', tool_input: {} },
        { type: 'tool_result', seq: 5, tool_id: 't1', tool_result: 'a b', tool_status: 'complete' },
        { type: 'content', seq: 6, content: 'three.', ...routing },
        { type: 'done', seq: 7, session_id: 's-owned', ...routing },
    ],
};

/** The events with `from <= seq <= to` as SSE; `end` adds the stream's closing marker. */
export function ownedSlice(from: number, to: number, end = false): string {
    const body = ownedTurn.events
        .filter((e) => e.seq >= from && e.seq <= to)
        .map((e) => sse(e))
        .join('');
    return end ? `${body}data: [DONE]\n\n` : body;
}

export const interruptedReplay =
    sse({ type: 'error', seq: 4, error: 'Turn interrupted: the backend stopped while it was running', code: 'turn_interrupted', session_id: 's-owned' }) +
    'data: [DONE]\n\n';

export const idleReplay =
    sse({ type: 'idle', session_id: 's-owned', last_state: 'completed', turn_id: 'turn-1', ended_at: '2026-10-28T20:00:00+00:00' }) +
    'data: [DONE]\n\n';
