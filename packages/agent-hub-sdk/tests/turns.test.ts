// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import {
    AgentHubError,
    applyTurnEvent,
    createClient,
    createTurnState,
    isAbortError,
    type TurnEvent,
    type TurnRequest,
} from '../src';
import { cancelTurn, errorTurn, recordedPong, retryTurn, toolTurn } from './fixtures/turns';
import { byteSlices, collect, jsonResponse, mockFetch, slices, sseResponse } from './helpers';

const request: TurnRequest = {
    agent_slug: 'chat',
    project_id: 'agent-hub',
    messages: [{ role: 'user', content: 'hi' }],
};

function clientFor(fetch: ReturnType<typeof mockFetch>) {
    return createClient({ baseUrl: 'http://hub.test/', fetch });
}

const types = (events: TurnEvent[]) => events.map((e) => e.type);

describe('turns.stream', () => {
    it('posts the request as a stream and yields typed events up to done', async () => {
        const fetch = mockFetch(sseResponse([recordedPong]));
        const events = await collect(clientFor(fetch).turns.stream(request));

        expect(fetch.requests[0]).toMatchObject({
            url: 'http://hub.test/api/complete',
            method: 'POST',
            body: { ...request, stream: true },
        });
        expect(fetch.requests[0]!.headers.Accept).toBe('text/event-stream');
        expect(types(events)).toEqual(['connected', ...Array(5).fill('thinking'), 'content', 'content', 'done']);
        const done = events.at(-1)!;
        expect(done).toMatchObject({
            type: 'done',
            agent_used: 'provider-liveness-probe',
            model_used: 'nvidia/nemotron-3.5-lightning-30b-a3b',
            fallback_used: false,
            finish_reason: 'stop',
        });
    });

    it.each([1, 2, 7, 64])('gives the same events when the body is read in pieces of %i characters', async (size) => {
        const whole = await collect(clientFor(mockFetch(sseResponse([toolTurn]))).turns.stream(request));
        const split = await collect(clientFor(mockFetch(sseResponse(slices(toolTurn, size)))).turns.stream(request));
        expect(split).toEqual(whole);
        expect(types(split)).toEqual([
            'connected',
            'content',
            'tool_use',
            'tool_start',
            'tool_result',
            'content',
            'done',
        ]);
    });

    it('keeps multi-byte characters intact when a read cuts through one', async () => {
        const text = `data: ${JSON.stringify({ type: 'content', seq: 1, content: 'héllo 🌍 世界' })}\n\n`;
        const done = `data: ${JSON.stringify({ type: 'done', seq: 2, session_id: 's' })}\n\n`;
        const events = await collect(
            clientFor(mockFetch(sseResponse(byteSlices(text + done, 3)))).turns.stream(request),
        );
        expect(events[0]).toMatchObject({ type: 'content', content: 'héllo 🌍 世界' });
    });

    it('drops events whose seq it has already seen', async () => {
        const e = (seq: number, content: string) => `data: ${JSON.stringify({ type: 'content', seq, content })}\n\n`;
        const body =
            e(1, 'a') + e(2, 'b') + e(2, 'b-again') + e(1, 'a-again') + e(3, 'c') +
            `data: ${JSON.stringify({ type: 'done', seq: 4, session_id: 's' })}\n\n`;
        const events = await collect(clientFor(mockFetch(sseResponse(slices(body, 11)))).turns.stream(request));
        expect(events.filter((x) => x.type === 'content').map((x) => (x as { content: string }).content)).toEqual([
            'a',
            'b',
            'c',
        ]);
    });

    it('ends at the first terminal event and closes the connection', async () => {
        const onCancel = vi.fn();
        const body = sseResponse([errorTurn, 'data: {"type":"content","seq":9,"content":"late"}\n\n'], { onCancel, hang: true });
        const events = await collect(clientFor(mockFetch(body)).turns.stream(request));
        expect(types(events)).toEqual(['connected', 'content', 'error']);
        expect(events.at(-1)).toMatchObject({ type: 'error', error: 'Rate limit exceeded' });
        expect(onCancel).toHaveBeenCalled();
    });

    it('yields cancel_acknowledged as the last event of a cancelled turn', async () => {
        const events = await collect(clientFor(mockFetch(sseResponse([cancelTurn]))).turns.stream(request));
        expect(events.at(-1)).toMatchObject({ type: 'cancel_acknowledged', session_id: 's-cancel' });
    });

    it('delivers a final event the stream cut off before its blank line', async () => {
        const body = toolTurn.replace('data: [DONE]\n\n', '').replace(/\n\n$/, '');
        const events = await collect(clientFor(mockFetch(sseResponse([body]))).turns.stream(request));
        expect(events.at(-1)?.type).toBe('done');
    });

    it('throws stream_interrupted when the stream ends before a terminal event', async () => {
        const cut = toolTurn.split('data: {"type":"done"')[0]!;
        const run = collect(clientFor(mockFetch(sseResponse([cut]))).turns.stream(request));
        await expect(run).rejects.toMatchObject({ name: 'AgentHubError', code: 'stream_interrupted' });
    });

    it('throws stream_interrupted when the connection breaks mid-body', async () => {
        let reads = 0;
        const broken = new Response(
            new ReadableStream({
                pull(controller) {
                    if (reads++ === 0) {
                        controller.enqueue(new TextEncoder().encode('data: {"type":"connected","seq":1,"session_id":"s"}\n\n'));
                    } else {
                        controller.error(new Error('socket hang up'));
                    }
                },
            }),
        );
        const seen: string[] = [];
        const run = (async () => {
            for await (const e of clientFor(mockFetch(broken)).turns.stream(request)) seen.push(e.type);
        })();
        await expect(run).rejects.toMatchObject({ code: 'stream_interrupted', message: expect.stringContaining('socket hang up') });
        expect(seen).toEqual(['connected']);
    });

    it('reports unknown event types and bad JSON to onWarning and carries on', async () => {
        const body =
            'data: {"type":"cancelled","seq":1}\n\n' +
            'data: not json\n\n' +
            `data: ${JSON.stringify({ type: 'done', seq: 2, session_id: 's' })}\n\n`;
        const onWarning = vi.fn();
        const events = await collect(clientFor(mockFetch(sseResponse([body]))).turns.stream(request, { onWarning }));
        expect(types(events)).toEqual(['done']);
        expect(onWarning.mock.calls.map(([w]) => w.kind)).toEqual(['unknown_event', 'invalid_json']);
    });

    it('stops reading and closes the connection when the consumer leaves the loop', async () => {
        const onCancel = vi.fn();
        const fetch = mockFetch(sseResponse([toolTurn.slice(0, 200), toolTurn.slice(200)], { onCancel, hang: true }));
        for await (const event of clientFor(fetch).turns.stream(request)) {
            expect(event.type).toBe('connected');
            break;
        }
        expect(onCancel).toHaveBeenCalled();
        expect(fetch.requests[0]!.signal?.aborted).toBe(true);
    });

    it('rejects with AbortError and closes the connection when the signal aborts mid-stream', async () => {
        const controller = new AbortController();
        const fetch = mockFetch((req) => sseResponse([toolTurn.slice(0, 120)], { hang: true, signal: req.signal }));
        const seen: string[] = [];
        const run = (async () => {
            for await (const event of clientFor(fetch).turns.stream(request, { signal: controller.signal })) {
                seen.push(event.type);
                controller.abort();
            }
        })();
        const error = await run.catch((e: unknown) => e);
        expect(isAbortError(error)).toBe(true);
        expect(seen).toEqual(['connected']);
        expect(fetch.requests[0]!.signal?.aborted).toBe(true);
    });

    it('rejects at once when the signal is already aborted, without sending anything', async () => {
        const fetch = mockFetch(sseResponse([toolTurn]));
        const controller = new AbortController();
        controller.abort();
        const error = await collect(clientFor(fetch).turns.stream(request, { signal: controller.signal })).catch((e: unknown) => e);
        expect(isAbortError(error)).toBe(true);
        expect(fetch.requests).toHaveLength(0);
    });

    it('rejects with AbortError when the signal aborts while connecting', async () => {
        const controller = new AbortController();
        const fetch = mockFetch(
            (req) =>
                new Promise<Response>((_, reject) => {
                    req.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
                }),
        );
        const run = collect(clientFor(fetch).turns.stream(request, { signal: controller.signal }));
        await new Promise((r) => setTimeout(r, 5)); // let the request go out
        controller.abort();
        expect(isAbortError(await run.catch((e: unknown) => e))).toBe(true);
    });
});

describe('turns.stream errors', () => {
    it('turns an error response into an AgentHubError with its code, message and details', async () => {
        const fetch = mockFetch(
            jsonResponse(
                { error: 'client_not_found', message: 'Client not found', details: [{ hint: 'register' }] },
                403,
            ),
        );
        const error = await collect(clientFor(fetch).turns.stream(request)).catch((e: unknown) => e);
        expect(error).toBeInstanceOf(AgentHubError);
        expect(error).toMatchObject({
            status: 403,
            code: 'client_not_found',
            message: 'Client not found',
            details: [{ hint: 'register' }],
        });
    });

    it('reads the FastAPI detail shapes', async () => {
        const nested = mockFetch(jsonResponse({ detail: { code: 'not_found', message: 'run not found' } }, 404));
        await expect(collect(clientFor(nested).turns.stream(request))).rejects.toMatchObject({
            status: 404,
            code: 'not_found',
            message: 'run not found',
        });
        const text = mockFetch(jsonResponse({ detail: 'Unprocessable' }, 422));
        await expect(collect(clientFor(text).turns.stream(request))).rejects.toMatchObject({
            status: 422,
            code: 'http_error',
            message: 'Unprocessable',
        });
    });

    it('wraps a failed connection as network_error', async () => {
        const fetch = mockFetch([new TypeError('fetch failed')]);
        await expect(collect(clientFor(fetch).turns.stream(request))).rejects.toMatchObject({
            code: 'network_error',
            status: 0,
        });
    });
});

describe('turns.stream connectRetry', () => {
    const retry = { attempts: 3, initialDelayMs: 1, maxDelayMs: 2, jitter: 0 };

    it('retries network failures, 5xx and 429 before the response opens, then streams', async () => {
        const fetch = mockFetch([
            new TypeError('fetch failed'),
            jsonResponse({ error: 'overloaded', message: 'busy' }, 503),
            jsonResponse({ error: 'rate_limited', message: 'slow down' }, 429),
            sseResponse([toolTurn]),
        ]);
        const onRetry = vi.fn();
        const events = await collect(clientFor(fetch).turns.stream(request, { connectRetry: retry, onRetry }));
        expect(events.at(-1)?.type).toBe('done');
        expect(fetch.requests).toHaveLength(4);
        expect(onRetry.mock.calls.map(([i]) => i.attempt)).toEqual([1, 2, 3]);
    });

    it('does not retry a 4xx, and gives up after the allowed attempts', async () => {
        const bad = mockFetch(jsonResponse({ error: 'validation_error', message: 'bad' }, 422));
        await expect(collect(clientFor(bad).turns.stream(request, { connectRetry: retry }))).rejects.toMatchObject({ status: 422 });
        expect(bad.requests).toHaveLength(1);

        const down = mockFetch(() => jsonResponse({ error: 'down', message: 'down' }, 502));
        await expect(collect(clientFor(down).turns.stream(request, { connectRetry: retry }))).rejects.toMatchObject({ status: 502 });
        expect(down.requests).toHaveLength(4);
    });

    it('never retries once the stream is open', async () => {
        const cut = toolTurn.split('data: {"type":"done"')[0]!;
        const fetch = mockFetch(() => sseResponse([cut]));
        await expect(collect(clientFor(fetch).turns.stream(request, { connectRetry: retry }))).rejects.toMatchObject({
            code: 'stream_interrupted',
        });
        expect(fetch.requests).toHaveLength(1);
    });
});

describe('turn state', () => {
    async function assemble(body: string) {
        let state = createTurnState();
        for await (const event of clientFor(mockFetch(sseResponse(slices(body, 13)))).turns.stream(request)) {
            state = applyTurnEvent(state, event);
        }
        return state;
    }

    it('assembles content, tools and routing', async () => {
        const state = await assemble(toolTurn);
        expect(state).toMatchObject({
            status: 'done',
            sessionId: 's-tool',
            content: 'Let me look. It says hello.',
            routing: { agent_used: 'chat', fallback_used: false },
        });
        expect(state.tools).toEqual([
            { id: 't1', name: 'read_file', input: { path: 'a.txt' }, status: 'complete', started: true, result: 'hello' },
        ]);
    });

    it('turn_retry voids the partial output of the interrupted model turn only', async () => {
        const state = await assemble(retryTurn);
        expect(state.content).toBe('First turn. Second try.');
        expect(state.thinking).toBe('');
        expect(state.tools).toHaveLength(1);
        expect(state.retries).toBe(1);
        expect(state.status).toBe('done');
    });

    it('marks error and cancelled turns', async () => {
        expect(await assemble(errorTurn)).toMatchObject({ status: 'error', content: 'Partial', error: { error: 'Rate limit exceeded' } });
        expect(await assemble(cancelTurn)).toMatchObject({ status: 'cancelled', content: 'Working on' });
    });

    it('does not change the state it was given', () => {
        const before = createTurnState();
        const after = applyTurnEvent(before, { type: 'content', seq: 1, content: 'x' });
        expect(before.content).toBe('');
        expect(after.content).toBe('x');
    });
});

describe('turns.run', () => {
    it('returns the assembled turn and reports each event', async () => {
        const seen: Array<[string, string]> = [];
        const state = await clientFor(mockFetch(sseResponse([toolTurn]))).turns.run(request, {
            onEvent: (event, s) => seen.push([event.type, s.content]),
        });
        expect(state.content).toBe('Let me look. It says hello.');
        expect(seen[1]).toEqual(['content', 'Let me look. ']);
        expect(seen.at(-1)![0]).toBe('done');
    });

    it('rejects with a turn_error carrying the error event', async () => {
        const error = await clientFor(mockFetch(sseResponse([errorTurn]))).turns.run(request).catch((e: unknown) => e);
        expect(error).toMatchObject({ code: 'turn_error', message: 'Rate limit exceeded' });
        expect((error as AgentHubError).details).toMatchObject({ type: 'error', session_id: 's-err' });
    });

    it('resolves, not rejects, for a cancelled turn', async () => {
        const state = await clientFor(mockFetch(sseResponse([cancelTurn]))).turns.run(request);
        expect(state.status).toBe('cancelled');
    });
});

describe('turns.cancel', () => {
    it('posts the session id and returns whether the backend found a turn to stop', async () => {
        const fetch = mockFetch(jsonResponse({ cancelled: true, session_id: 's1' }));
        const result = await clientFor(fetch).turns.cancel('s1');
        expect(result).toEqual({ cancelled: true, session_id: 's1' });
        expect(fetch.requests[0]).toMatchObject({
            url: 'http://hub.test/api/complete/cancel',
            method: 'POST',
            body: { session_id: 's1' },
        });
    });
});
