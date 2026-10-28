import { createAgentsApi, createModelsApi, type AgentsApi, type ModelsApi } from './catalog';
import { createEventsApi, eventsUrl, type EventsApi } from './events';
import { createTransport, type FetchLike, type HeaderSource } from './http';
import { createSessionsApi, type SessionsApi } from './sessions';
import { createTurnsApi, type TurnsApi } from './turns';
import type { WebSocketFactory } from './types/events';
import { createWorkflowRunsApi, type WorkflowRunsApi } from './workflow-runs';

/** Sent by the dashboard on every request so the backend can attribute it. */
export const CLIENT_ID_HEADER = 'X-Client-Id';
export const REQUEST_SOURCE_HEADER = 'X-Request-Source';
/** The owner credential. The SDK only passes headers on; it never reads token files. */
export const OWNER_TOKEN_HEADER = 'X-Agent-Hub-Owner-Token';

export interface ClientOptions {
    /**
     * Where Agent Hub is, e.g. `http://localhost:8003`. Use `''` in a browser for same-origin requests (the dashboard's
     * proxy). A trailing slash is ignored.
     */
    baseUrl: string;
    /**
     * The `fetch` to use, so a host can route requests through its own stack (Aico sends them through its main
     * process). Defaults to the platform `fetch`.
     */
    fetch?: FetchLike;
    /** Sent as `X-Client-Id`. The backend rejects turns from a client that is not registered. */
    clientId?: string;
    /** Sent as `X-Request-Source` (which app is calling), required together with `clientId`. */
    requestSource?: string;
    /**
     * Headers for every request (and for the events socket where the platform allows it): an object, or a function
     * called per request when the values can change (a rotated token).
     */
    headers?: HeaderSource;
    /** The `WebSocket` to use for {@link AgentHubClient.events}. Defaults to the platform `WebSocket`. */
    webSocket?: WebSocketFactory;
}

export interface AgentHubClient {
    readonly baseUrl: string;
    readonly sessions: SessionsApi;
    readonly models: ModelsApi;
    readonly agents: AgentsApi;
    readonly turns: TurnsApi;
    readonly events: EventsApi;
    readonly workflowRuns: WorkflowRunsApi;
}

export function createClient(options: ClientOptions): AgentHubClient {
    const identity: Record<string, string> = {};
    if (options.clientId) identity[CLIENT_ID_HEADER] = options.clientId;
    if (options.requestSource) identity[REQUEST_SOURCE_HEADER] = options.requestSource;
    const extra = options.headers;
    const transport = createTransport({
        baseUrl: options.baseUrl,
        fetch: options.fetch,
        headers: async () => ({ ...identity, ...(typeof extra === 'function' ? await extra() : extra) }),
    });
    return {
        baseUrl: transport.baseUrl,
        sessions: createSessionsApi(transport),
        models: createModelsApi(transport),
        agents: createAgentsApi(transport),
        turns: createTurnsApi(transport),
        events: createEventsApi({
            // Resolved on first use so a relative baseUrl works as long as a page exists by then.
            get url() {
                return eventsUrl(transport.baseUrl);
            },
            headers: transport.headers,
            webSocket: options.webSocket,
        }),
        workflowRuns: createWorkflowRunsApi(transport),
    };
}
