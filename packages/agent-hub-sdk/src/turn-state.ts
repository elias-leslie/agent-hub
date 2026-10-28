import type {
    DoneEvent,
    ToolStatus,
    TurnErrorEvent,
    TurnEvent,
    TurnRouting,
} from './types/turns';

export interface ToolCall {
    id: string;
    name: string;
    input: Record<string, unknown>;
    status: ToolStatus;
    /** True once the backend reported it began executing the tool. */
    started: boolean;
    result?: string;
}

export type TurnStatus = 'streaming' | 'done' | 'cancelled' | 'error';

/** A turn as the events so far describe it. Built with {@link applyTurnEvent}; every update returns a new object. */
export interface TurnState {
    status: TurnStatus;
    sessionId?: string;
    /** The answer text, with the partial output of any retried model turn already removed. */
    content: string;
    thinking: string;
    tools: ToolCall[];
    /** How many `turn_retry` events arrived. */
    retries: number;
    /** The model that answered and whether a fallback served it, once known. */
    routing: TurnRouting;
    done?: DoneEvent;
    error?: TurnErrorEvent;
    /** Where the current model turn began (after the last tool result); a retry cuts back to here. */
    turnStart: { content: number; thinking: number; tools: number };
}

export function createTurnState(): TurnState {
    return {
        status: 'streaming',
        content: '',
        thinking: '',
        tools: [],
        retries: 0,
        routing: {},
        turnStart: { content: 0, thinking: 0, tools: 0 },
    };
}

function routingOf(event: TurnRouting): TurnRouting {
    const out: TurnRouting = {};
    if (event.model !== undefined) out.model = event.model;
    if (event.provider !== undefined) out.provider = event.provider;
    if (event.agent_used !== undefined) out.agent_used = event.agent_used;
    if (event.model_used !== undefined) out.model_used = event.model_used;
    if (event.fallback_used !== undefined) out.fallback_used = event.fallback_used;
    if (event.fallback_reason !== undefined) out.fallback_reason = event.fallback_reason;
    return out;
}

export function applyTurnEvent(state: TurnState, event: TurnEvent): TurnState {
    switch (event.type) {
        case 'connected':
            return { ...state, sessionId: event.session_id };
        case 'content':
            return {
                ...state,
                content: state.content + event.content,
                routing: { ...state.routing, ...routingOf(event) },
            };
        case 'thinking':
            return { ...state, thinking: state.thinking + event.content };
        case 'tool_use':
            return {
                ...state,
                tools: [
                    ...state.tools,
                    {
                        id: event.tool_id,
                        name: event.tool_name,
                        input: event.tool_input ?? {},
                        status: 'running',
                        started: false,
                    },
                ],
            };
        case 'tool_start':
            return {
                ...state,
                tools: state.tools.map((t) => (t.id === event.tool_id ? { ...t, started: true } : t)),
            };
        case 'tool_result': {
            const tools = state.tools.map((t) =>
                t.id === event.tool_id
                    ? { ...t, status: event.tool_status, result: event.tool_result }
                    : t,
            );
            // The next model turn starts after its tools' results.
            return {
                ...state,
                tools,
                turnStart: {
                    content: state.content.length,
                    thinking: state.thinking.length,
                    tools: tools.length,
                },
            };
        }
        case 'turn_retry':
            // The interrupted model turn's partial output is void.
            return {
                ...state,
                content: state.content.slice(0, state.turnStart.content),
                thinking: state.thinking.slice(0, state.turnStart.thinking),
                tools: state.tools.slice(0, state.turnStart.tools),
                retries: state.retries + 1,
            };
        case 'cancel_acknowledged':
            return { ...state, status: 'cancelled', sessionId: event.session_id || state.sessionId };
        case 'done':
            return {
                ...state,
                status: 'done',
                done: event,
                sessionId: event.session_id || state.sessionId,
                routing: { ...state.routing, ...routingOf(event) },
            };
        case 'error':
            return { ...state, status: 'error', error: event };
    }
}
