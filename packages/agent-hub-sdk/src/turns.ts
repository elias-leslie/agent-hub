import { abortError, AgentHubError, isAbortError } from './errors';
import { sleep, type Transport } from './http';
import { readTextChunks, SseParser } from './sse';
import { applyTurnEvent, createTurnState, type TurnState } from './turn-state';
import type { TerminalTurnEvent, TurnEvent, TurnEventType, TurnRequest } from './types/turns';

const EVENT_TYPES: ReadonlySet<string> = new Set<TurnEventType>([
    'connected',
    'content',
    'thinking',
    'tool_use',
    'tool_start',
    'tool_result',
    'turn_retry',
    'cancel_acknowledged',
    'done',
    'error',
]);

/**
 * Retry the connect step only: network failures, 5xx and 429 before the backend has accepted the request. Once the
 * response is open nothing is retried, because the backend cannot resume a turn and a second POST would run it twice.
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
    /** Events the SDK skipped: a type it does not know, or data that is not JSON. */
    onWarning?: (warning: StreamWarning) => void;
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
     * connection ends before one ({@link AgentHubError} with code `stream_interrupted`).
     * Leaving the loop early (`break`) closes the connection.
     */
    stream(request: TurnRequest, options?: StreamOptions): AsyncGenerator<TurnEvent, void, undefined>;
    /** Stream a turn to its end and return it assembled. Throws {@link AgentHubError} (code `turn_error`) on an `error` event. */
    run(request: TurnRequest, options?: RunOptions): Promise<TurnState>;
    /** Ask the backend to stop an active turn after the tool it is running. */
    cancel(sessionId: string): Promise<CancelResult>;
}

export function isTerminalTurnEvent(event: TurnEvent): event is TerminalTurnEvent {
    return event.type === 'done' || event.type === 'error' || event.type === 'cancel_acknowledged';
}

export function createTurnsApi(transport: Transport): TurnsApi {
    async function connect(request: TurnRequest, options: StreamOptions, signal: AbortSignal): Promise<Response> {
        const retry = options.connectRetry;
        for (let attempt = 0; ; attempt++) {
            try {
                return await transport.send('POST', '/api/complete', {
                    body: { ...request, stream: true },
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

    async function* stream(request: TurnRequest, options: StreamOptions = {}) {
        const outer = options.signal;
        if (outer?.aborted) throw abortError(outer);
        // One signal for the fetch: the caller's abort, or ours when the consumer stops early.
        const controller = new AbortController();
        const onAbort = () => controller.abort(outer?.reason);
        outer?.addEventListener('abort', onAbort, { once: true });
        try {
            const response = await connect(request, options, controller.signal);
            if (!response.body) {
                throw new AgentHubError({
                    message: 'Agent Hub answered without a response body',
                    status: response.status,
                    code: 'invalid_response',
                });
            }
            const parser = new SseParser();
            let lastSeq = Number.NEGATIVE_INFINITY;
            let finished = false;

            const decode = (data: string): TurnEvent | null => {
                if (data === '[DONE]') return null;
                let parsed: unknown;
                try {
                    parsed = JSON.parse(data);
                } catch {
                    options.onWarning?.({ kind: 'invalid_json', data });
                    return null;
                }
                const type = (parsed as { type?: unknown } | null)?.type;
                if (typeof type !== 'string' || !EVENT_TYPES.has(type)) {
                    options.onWarning?.({ kind: 'unknown_event', data });
                    return null;
                }
                const event = parsed as TurnEvent;
                if (typeof event.seq === 'number') {
                    if (event.seq <= lastSeq) return null;
                    lastSeq = event.seq;
                }
                return event;
            };

            try {
                for await (const chunk of readTextChunks(response.body)) {
                    for (const data of parser.push(chunk)) {
                        const event = decode(data);
                        if (!event) continue;
                        yield event;
                        if (isTerminalTurnEvent(event)) {
                            finished = true;
                            return;
                        }
                    }
                }
                for (const data of parser.flush()) {
                    const event = decode(data);
                    if (!event) continue;
                    yield event;
                    if (isTerminalTurnEvent(event)) {
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
        } finally {
            outer?.removeEventListener('abort', onAbort);
            controller.abort();
        }
    }

    return {
        stream,

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

function backoff(attempt: number, retry: ConnectRetry): number {
    const initial = retry.initialDelayMs ?? 1000;
    const max = retry.maxDelayMs ?? 30000;
    const base = Math.min(initial * 2 ** attempt, max);
    return Math.round(base + base * (retry.jitter ?? 0.2) * Math.random());
}
