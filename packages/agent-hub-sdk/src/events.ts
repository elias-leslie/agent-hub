import { sleep } from './http';
import type {
    ConnectionStatus,
    EventFilters,
    LiveEvent,
    WebSocketFactory,
    WebSocketLike,
} from './types/events';

export interface SubscribeOptions extends EventFilters {
    /** Reconnect with backoff after the socket drops, and subscribe again with the latest filters. Default true. */
    reconnect?: boolean;
    /** First reconnect delay, doubling to `maxReconnectDelayMs`. Default 1000. */
    reconnectDelayMs?: number;
    maxReconnectDelayMs?: number;
    onStatus?: (status: ConnectionStatus) => void;
    /** A socket error, or an error message the server sent for the subscription. */
    onError?: (message: string) => void;
}

export interface Subscription {
    /** Resolves when the server confirms the first subscription; rejects if closed before that. */
    readonly ready: Promise<void>;
    readonly status: ConnectionStatus;
    /** Change the filters of the live subscription (and of later reconnects). */
    update(filters: EventFilters): void;
    /** Stop for good: closes the socket and cancels any pending reconnect. */
    close(): void;
}

export interface EventsApi {
    /** Subscribe to live session events (owner only). The handler gets each event as it arrives. */
    subscribe(handler: (event: LiveEvent) => void, options?: SubscribeOptions): Subscription;
}

const LIVE_EVENT_TYPES: ReadonlySet<string> = new Set([
    'session_start',
    'message',
    'tool_use',
    'tool_result',
    'complete',
    'error',
]);

export function createEventsApi(deps: {
    /** Full `ws://` / `wss://` address of the events socket (see {@link eventsUrl}). */
    url: string;
    headers(): Promise<Record<string, string>>;
    webSocket?: WebSocketFactory;
}): EventsApi {
    return {
        subscribe(handler, options = {}) {
            let filters: EventFilters = {
                sessionIds: options.sessionIds,
                eventTypes: options.eventTypes,
            };
            let status: ConnectionStatus = 'connecting';
            let socket: WebSocketLike | null = null;
            let closed = false;
            let delay = options.reconnectDelayMs ?? 1000;
            const maxDelay = options.maxReconnectDelayMs ?? 30000;
            const reconnect = options.reconnect ?? true;
            const wake = new AbortController();
            let confirmed = false;
            let resolveReady!: () => void;
            let rejectReady!: (error: Error) => void;
            const ready = new Promise<void>((resolve, reject) => {
                resolveReady = resolve;
                rejectReady = reject;
            });
            ready.catch(() => undefined); // a caller that never awaits `ready` must not see an unhandled rejection

            const setStatus = (next: ConnectionStatus) => {
                if (status === next) return;
                status = next;
                options.onStatus?.(next);
            };

            const frame = (type: 'subscribe' | 'update') => ({
                type,
                session_ids: filters.sessionIds?.length ? filters.sessionIds : undefined,
                event_types: filters.eventTypes?.length ? filters.eventTypes : undefined,
            });

            const onMessage = (raw: unknown) => {
                if (typeof raw !== 'string') return;
                let data: unknown;
                try {
                    data = JSON.parse(raw);
                } catch {
                    return;
                }
                if (typeof data !== 'object' || data === null) return;
                const record = data as Record<string, unknown>;
                if (typeof record.event_type === 'string') {
                    if (LIVE_EVENT_TYPES.has(record.event_type)) handler(data as LiveEvent);
                    return;
                }
                if (record.type === 'subscribed') {
                    delay = options.reconnectDelayMs ?? 1000;
                    setStatus('connected');
                    if (!confirmed) {
                        confirmed = true;
                        resolveReady();
                    }
                } else if (record.type === 'error') {
                    options.onError?.(typeof record.message === 'string' ? record.message : 'Subscription error');
                }
            };

            const open = async () => {
                let headers: Record<string, string> = {};
                try {
                    headers = await deps.headers();
                    if (closed) return;
                    const factory = deps.webSocket ?? defaultWebSocket;
                    const ws = factory(deps.url, { headers });
                    socket = ws;
                    ws.onopen = () => ws.send(JSON.stringify(frame('subscribe')));
                    ws.onmessage = (event) => onMessage(event.data);
                    ws.onerror = () => options.onError?.('WebSocket connection error');
                    ws.onclose = () => {
                        if (socket !== ws) return;
                        socket = null;
                        if (closed) return;
                        if (!reconnect) return finish();
                        setStatus('reconnecting');
                        const wait = delay;
                        delay = Math.min(delay * 2, maxDelay);
                        sleep(wait, wake.signal).then(open, () => undefined);
                    };
                } catch (error) {
                    options.onError?.(error instanceof Error ? error.message : String(error));
                    if (!closed && reconnect) {
                        setStatus('reconnecting');
                        const wait = delay;
                        delay = Math.min(delay * 2, maxDelay);
                        sleep(wait, wake.signal).then(open, () => undefined);
                    } else {
                        finish();
                    }
                }
            };

            const finish = () => {
                closed = true;
                wake.abort();
                setStatus('closed');
                if (!confirmed) rejectReady(new Error('Subscription closed before it was confirmed'));
            };

            void open();

            return {
                ready,
                get status() {
                    return status;
                },
                update(next) {
                    filters = next;
                    if (socket && status === 'connected') socket.send(JSON.stringify(frame('update')));
                },
                close() {
                    if (closed) return;
                    const ws = socket;
                    socket = null;
                    finish();
                    try {
                        ws?.close(1000);
                    } catch {
                        // already closed
                    }
                },
            };
        },
    };
}

/** `/api/events` on the same host as `baseUrl`, over ws:// or wss://. A relative base resolves against the page. */
export function eventsUrl(baseUrl: string): string {
    const path = '/api/events';
    if (/^https?:\/\//i.test(baseUrl)) return baseUrl.replace(/^http/i, 'ws') + path;
    const location = (globalThis as { location?: { protocol: string; host: string } }).location;
    if (!location) throw new Error('baseUrl must be absolute outside a browser');
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${scheme}//${location.host}${baseUrl}${path}`;
}

/**
 * The platform `WebSocket`. Outside a browser (Electron main, Node) it also gets the client's headers, which both
 * undici's `WebSocket` and `ws` accept as a second argument; in a browser that argument would be read as the protocol
 * list, so it is left out there.
 */
export const defaultWebSocket: WebSocketFactory = (url, { headers }) => {
    const Ctor = (globalThis as { WebSocket?: new (url: string, init?: unknown) => WebSocketLike }).WebSocket;
    if (!Ctor) throw new Error('No WebSocket available: pass `webSocket` to createClient');
    const inBrowser = typeof (globalThis as { document?: unknown }).document !== 'undefined';
    return !inBrowser && Object.keys(headers).length ? new Ctor(url, { headers }) : new Ctor(url);
};
