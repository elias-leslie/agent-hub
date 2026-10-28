import { pathSegment, type Transport } from './http';
import type {
    CloseSessionResult,
    ForkSessionRequest,
    ForkSessionResult,
    ListSessionsParams,
    Session,
    SessionCreateRequest,
    SessionEventsPage,
    SessionEventsParams,
    SessionList,
    SessionMessage,
} from './types/sessions';

interface CallOptions {
    signal?: AbortSignal;
}

export interface SessionsApi {
    /** Idempotent when `session_id` is given: an existing session is returned. */
    create(request: SessionCreateRequest, options?: CallOptions): Promise<Session>;
    /** The session with its messages; `includeMessages: false` returns the summary only (counts, no messages). */
    get(id: string, options?: CallOptions & { includeMessages?: boolean }): Promise<Session>;
    list(params?: ListSessionsParams, options?: CallOptions): Promise<SessionList>;
    /** Idempotent. Also stops a turn that is still streaming for the session. */
    close(id: string, options?: CallOptions): Promise<CloseSessionResult>;
    /** A copy of the session up to a turn, as a new session. */
    fork(id: string, request?: ForkSessionRequest, options?: CallOptions): Promise<ForkSessionResult>;
    /** The session's stored messages. */
    messages(id: string, options?: CallOptions): Promise<SessionMessage[]>;
    /** The session timeline (turns, tool calls, usage), one window at a time; continue with `next_after`. */
    events(id: string, params?: SessionEventsParams, options?: CallOptions): Promise<SessionEventsPage>;
}

export function createSessionsApi(transport: Transport): SessionsApi {
    const base = (id: string) => `/api/sessions/${pathSegment(id)}`;
    return {
        create: (request, options) =>
            transport.json('POST', '/api/sessions', { body: request, signal: options?.signal }),
        get: (id, options) =>
            transport.json('GET', base(id), {
                query: options?.includeMessages === false ? { include_events: false } : undefined,
                signal: options?.signal,
            }),
        list: (params, options) =>
            transport.json('GET', '/api/sessions', { query: params, signal: options?.signal }),
        close: (id, options) => transport.json('POST', `${base(id)}/close`, { signal: options?.signal }),
        fork: (id, request, options) =>
            transport.json('POST', `${base(id)}/fork`, { body: request ?? {}, signal: options?.signal }),
        async messages(id, options) {
            const session = await transport.json<Session>('GET', base(id), { signal: options?.signal });
            return session.messages ?? [];
        },
        events: (id, params, options) =>
            transport.json('GET', `${base(id)}/events`, { query: params, signal: options?.signal }),
    };
}
