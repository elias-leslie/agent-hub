import { abortError, AgentHubError, isAbortError } from './errors';
import { pathSegment, sleep, type Transport } from './http';
import { readTextChunks, SseParser } from './sse';
import { applyTurnEvent, createTurnState, type TurnState } from './turn-state';
import type { IdleEvent, TerminalTurnEvent, TurnEvent, TurnEventType, TurnRequest } from './types/turns';

const EVENT_TYPES: ReadonlySet<string> = new Set<TurnEventType>([
    'connected',
    'content',
    'thinking',
    'tool_use',
    'tool_start',
    'tool_result',
    'turn_retry',
    'context_compacted',
    'cancel_acknowledged',
    'done',
    'error',
]);

/**
 * Retry the connect step only: network failures, 5xx and 429 before the backend has accepted the request. Once the
 * response is open the POST is never repeated (it would run the turn twice); a lost connection is handled by
 * {@link ReattachPolicy} instead, which follows the turn the server is still running.
 */
export interface ConnectRetry {
    /** Retries after the first attempt. */
    attempts: number;
    /** First delay; doubles each retry. Default 1000. */
    initialDelayMs?: number;
    /** Cap on the delay. Default 30000. */
    maxDelayMs?: number;
    /** Random extra delay as a fraction of it, 0 to 1. Default 0.2. */
    jitter?: number;
}

/**
 * What `turns.stream` and `turns.attach` do when the connection drops before the turn's last event: the turn keeps
 * running on the server, so they reconnect with `GET /api/sessions/{id}/stream?after_seq=<last seq seen>` and carry
 * on. The tries are bounded: `attempts` reconnects in a row without a new event arriving (any event resets the
 * count). Out of tries, or when the server refuses (the turn is gone: 404, 409, 410), the original
 * {@link AgentHubError} (`stream_interrupted`) or the refusal is thrown.
 */
export interface ReattachPolicy {
    /** Reconnects in a row without progress. Default 5. */
    attempts: number;
    /** First delay; doubles each try. Default 500. */
    initialDelayMs?: number;
    /** Cap on the delay. Default 10000. */
    maxDelayMs?: number;
    /** Random extra delay as a fraction of it, 0 to 1. Default 0.2. */
    jitter?: number;
}

export const DEFAULT_REATTACH: ReattachPolicy = { attempts: 5, initialDelayMs: 500, maxDelayMs: 10000, jitter: 0.2 };

export interface StreamWarning {
    kind: 'unknown_event' | 'invalid_json';
    /** The raw `data` payload. */
    data: string;
}

export interface StreamOptions {
    /** Aborting closes the connection and rejects the iterator with an `AbortError`. It does not cancel the turn on the server; use {@link TurnsApi.cancel}. */
    signal?: AbortSignal;
    connectRetry?: ConnectRetry;
    onRetry?: (info: { attempt: number; delayMs: number; error: AgentHubError }) => void;
    /** Reconnect to the running turn when the connection drops. On by default ({@link DEFAULT_REATTACH}); `false` turns it off. */
    reattach?: ReattachPolicy | false;
    /** Called before each reconnect, with the last `seq` the stream will resume after. */
    onReattach?: (info: { attempt: number; delayMs: number; afterSeq: number; error: AgentHubError }) => void;
    /** Events the SDK skipped: a type it does not know, or data that is not JSON. */
    onWarning?: (warning: StreamWarning) => void;
}

export interface AttachOptions extends StreamOptions {
    /** Replay events with `seq` greater than this. Default 0: the whole turn. */
    afterSeq?: number;
    /** Refuse (409 `turn_mismatch`) if the session's turn is not this one; a `connected` event carries its `turn_id`. */
    turnId?: string;
}

export interface RunOptions extends StreamOptions {
    /** Called for every event, in order, with the turn as it stands after that event. */
    onEvent?: (event: TurnEvent, state: TurnState) => void;
}

export interface CancelResult {
    cancelled: boolean;
    session_id: string;
}

export interface TurnsApi {
    /**
     * Start a turn and iterate its events. Events are deduplicated by `seq` (one already seen is dropped), the
     * iterator ends after the first terminal event (`done`, `error`, `cancel_acknowledged`), and it throws if the
     * connection ends before one and cannot be picked up again ({@link AgentHubError} with code
     * `stream_interrupted`). The turn runs on the server, so a dropped connection is reconnected to it
     * automatically from the last `seq` seen, within {@link ReattachPolicy}. Leaving the loop early (`break`) closes
     * the connection; the turn keeps running.
     */
    stream(request: TurnRequest, options?: StreamOptions): AsyncGenerator<TurnEvent, void, undefined>;
    /**
     * Pick up a session's running turn from any client: replays the events after `afterSeq`, then follows live
     * until the turn ends. Every subscriber sees the same stream. Same contract as {@link TurnsApi.stream}:
     * deduplicated by `seq`, ends after the first terminal event, `stream_interrupted` (after bounded reconnects)
     * if the connection ends earlier. With no turn running it yields one `idle` event (how the last turn ended),
     * or an `error` event with code `turn_interrupted` for a turn the backend restart cut off.
     */
    attach(sessionId: string, options?: AttachOptions): AsyncGenerator<TurnEvent | IdleEvent, void, undefined>;
    /** Stream a turn to its end and return it assembled. Throws {@link AgentHubError} (code `turn_error`) on an `error` event. */
    run(request: TurnRequest, options?: RunOptions): Promise<TurnState>;
    /** Ask the backend to stop an active turn after the tool it is running. */
    cancel(sessionId: string): Promise<CancelResult>;
}

export function isTerminalTurnEvent(event: TurnEvent): event is TerminalTurnEvent {
    return event.type === 'done' || event.type === 'error' || event.type === 'cancel_acknowledged';
}

const ATTACH_EVENT_TYPES: ReadonlySet<string> = new Set([...EVENT_TYPES, 'idle']);

type AnyTurnEvent = TurnEvent | IdleEvent;

function isTerminalAny(event: AnyTurnEvent): boolean {
    return event.type === 'idle' || isTerminalTurnEvent(event);
}

export function createTurnsApi(transport: Transport): TurnsApi {
    /** Open a request, retrying only the connect step (network failure, 5xx, 429) as `connectRetry` allows. */
    async function open(
        method: 'GET' | 'POST',
        path: string,
        init: { body?: unknown; query?: object },
        options: StreamOptions,
        signal: AbortSignal,
    ): Promise<Response> {
        const retry = options.connectRetry;
        for (let attempt = 0; ; attempt++) {
            try {
                return await transport.send(method, path, {
                    ...init,
                    headers: { Accept: 'text/event-stream' },
                    signal,
                });
            } catch (error) {
                if (!(error instanceof AgentHubError) || !retry || attempt >= retry.attempts) throw error;
                if (!retryable(error)) throw error;
                const delayMs = backoff(attempt, retry);
                options.onRetry?.({ attempt: attempt + 1, delayMs, error });
                await sleep(delayMs, signal);
            }
        }
    }

    const attachPath = (sessionId: string) => `/api/sessions/${pathSegment(sessionId)}/stream`;

    /** Read one response to its terminal event, sharing the `seq` cursor so a reconnect never repeats an event. */
    async function* readEvents(
        response: Response,
        cursor: { lastSeq: number },
        known: ReadonlySet<string>,
        options: StreamOptions,
        outer: AbortSignal | undefined,
    ): AsyncGenerator<AnyTurnEvent, void, undefined> {
        if (!response.body) {
            throw new AgentHubError({
                message: 'Agent Hub answered without a response body',
                status: response.status,
                code: 'invalid_response',
            });
        }
        const parser = new SseParser();
        const decode = (data: string): AnyTurnEvent | null => {
            if (data === '[DONE]') return null;
            let parsed: unknown;
            try {
                parsed = JSON.parse(data);
            } catch {
                options.onWarning?.({ kind: 'invalid_json', data });
                return null;
            }
            const type = (parsed as { type?: unknown } | null)?.type;
            if (typeof type !== 'string' || !known.has(type)) {
                options.onWarning?.({ kind: 'unknown_event', data });
                return null;
            }
            const event = parsed as AnyTurnEvent;
            if (typeof event.seq === 'number') {
                if (event.seq <= cursor.lastSeq) return null;
                cursor.lastSeq = event.seq;
            }
            return event;
        };

        let finished = false;
        try {
            for await (const chunk of readTextChunks(response.body)) {
                for (const data of parser.push(chunk)) {
                    const event = decode(data);
                    if (!event) continue;
                    yield event;
                    if (isTerminalAny(event)) {
                        finished = true;
                        return;
                    }
                }
            }
            for (const data of parser.flush()) {
                const event = decode(data);
                if (!event) continue;
                yield event;
                if (isTerminalAny(event)) {
                    finished = true;
                    return;
                }
            }
        } catch (error) {
            if (outer?.aborted || isAbortError(error)) throw abortError(outer);
            if (error instanceof AgentHubError) throw error;
            throw new AgentHubError({
                message: `Connection to Agent Hub lost mid-turn: ${error instanceof Error ? error.message : String(error)}`,
                code: 'stream_interrupted',
                cause: error,
            });
        }
        if (!finished) {
            throw new AgentHubError({
                message: 'The turn stream ended before the turn finished',
                code: 'stream_interrupted',
            });
        }
    }

    /**
     * Yield the events of `first`, and when the connection drops before the turn ends, reconnect through
     * `reconnect(lastSeq)` as often as the policy allows.
     */
    async function* drive(
        first: Response,
        reconnect: (afterSeq: number, turnId: string | undefined, signal: AbortSignal) => Promise<Response>,
        cursor: { lastSeq: number },
        known: ReadonlySet<string>,
        options: StreamOptions,
        outer: AbortSignal | undefined,
        signal: AbortSignal,
        target: { sessionId?: string; turnId?: string },
    ): AsyncGenerator<AnyTurnEvent, void, undefined> {
        const policy = options.reattach === undefined ? DEFAULT_REATTACH : options.reattach;
        let failures = 0;
        let response = first;
        for (;;) {
            let lost: AgentHubError;
            try {
                for await (const event of readEvents(response, cursor, known, options, outer)) {
                    failures = 0;
                    if (event.type === 'connected') {
                        target.sessionId = event.session_id;
                        target.turnId = event.turn_id ?? target.turnId;
                    }
                    yield event;
                }
                return;
            } catch (error) {
                if (!(error instanceof AgentHubError) || error.code !== 'stream_interrupted') throw error;
                if (!policy || !target.sessionId) throw error;
                lost = error;
            }
            // Reconnect: the turn is still running on the server.
            const interrupted = lost;
            for (;;) {
                if (failures >= policy.attempts) {
                    if (lost === interrupted) throw interrupted;
                    throw new AgentHubError({
                        message: `${interrupted.message}; ${failures} reconnects failed (last: ${lost.message})`,
                        code: 'stream_interrupted',
                        cause: lost,
                    });
                }
                const delayMs = backoff(failures, policy);
                failures += 1;
                options.onReattach?.({ attempt: failures, delayMs, afterSeq: cursor.lastSeq, error: lost });
                await sleep(delayMs, outer);
                try {
                    response = await reconnect(Math.max(cursor.lastSeq, 0), target.turnId, signal);
                    break;
                } catch (error) {
                    if (!(error instanceof AgentHubError) || !retryable(error)) throw error;
                    lost = error;
                }
            }
        }
    }

    function linked(outer: AbortSignal | undefined) {
        // One signal for the fetch: the caller's abort, or ours when the consumer stops early.
        const controller = new AbortController();
        const onAbort = () => controller.abort(outer?.reason);
        outer?.addEventListener('abort', onAbort, { once: true });
        return {
            signal: controller.signal,
            release() {
                outer?.removeEventListener('abort', onAbort);
                controller.abort();
            },
        };
    }

    async function* stream(request: TurnRequest, options: StreamOptions = {}) {
        const outer = options.signal;
        if (outer?.aborted) throw abortError(outer);
        const link = linked(outer);
        try {
            const first = await open('POST', '/api/complete', { body: { ...request, stream: true } }, options, link.signal);
            // Only a `connected` event names the turn to come back to; before it, a request's session may still hold an older turn.
            const target: { sessionId?: string; turnId?: string } = {};
            const reconnect = (afterSeq: number, turnId: string | undefined, signal: AbortSignal) =>
                open('GET', attachPath(target.sessionId!), { query: { after_seq: afterSeq, turn_id: turnId } }, options, signal);
            for await (const event of drive(first, reconnect, { lastSeq: Number.NEGATIVE_INFINITY }, ATTACH_EVENT_TYPES, options, outer, link.signal, target)) {
                if (event.type === 'idle') {
                    // Reconnected, but the server has no turn running any more and no longer holds its events.
                    throw new AgentHubError({
                        message: `The turn is no longer running on the server (last state: ${event.last_state}); read the session for its result`,
                        code: 'turn_not_running',
                        details: event,
                    });
                }
                yield event;
            }
        } finally {
            link.release();
        }
    }

    async function* attach(sessionId: string, options: AttachOptions = {}) {
        const outer = options.signal;
        if (outer?.aborted) throw abortError(outer);
        const link = linked(outer);
        try {
            const reconnect = (afterSeq: number, turnId: string | undefined, signal: AbortSignal) =>
                open('GET', attachPath(sessionId), { query: { after_seq: afterSeq, turn_id: turnId } }, options, signal);
            const first = await reconnect(options.afterSeq ?? 0, options.turnId, link.signal);
            const target = { sessionId, turnId: options.turnId };
            yield* drive(first, reconnect, { lastSeq: options.afterSeq ?? Number.NEGATIVE_INFINITY }, ATTACH_EVENT_TYPES, options, outer, link.signal, target);
        } finally {
            link.release();
        }
    }

    return {
        stream,
        attach,

        async run(request, options = {}) {
            const { onEvent, ...streamOptions } = options;
            let state = createTurnState();
            for await (const event of stream(request, streamOptions)) {
                state = applyTurnEvent(state, event);
                onEvent?.(event, state);
            }
            if (state.status === 'error' && state.error) {
                throw new AgentHubError({
                    message: state.error.error,
                    code: 'turn_error',
                    details: state.error,
                });
            }
            return state;
        },

        cancel(sessionId) {
            return transport.json<CancelResult>('POST', '/api/complete/cancel', {
                body: { session_id: sessionId },
            });
        },
    };
}

function retryable(error: AgentHubError): boolean {
    return error.code === 'network_error' || error.status >= 500 || error.status === 429;
}

function backoff(attempt: number, retry: ConnectRetry | ReattachPolicy): number {
    const initial = retry.initialDelayMs ?? 1000;
    const max = retry.maxDelayMs ?? 30000;
    const base = Math.min(initial * 2 ** attempt, max);
    return Math.round(base + base * (retry.jitter ?? 0.2) * Math.random());
}
