/** Codes the SDK itself raises (the server's own codes are free-form strings, e.g. `not_found`, `not_paused`). */
export type ClientErrorCode =
    | 'network_error'
    | 'stream_interrupted'
    | 'invalid_response'
    | 'turn_error'
    | 'http_error';

/**
 * Every failure from Agent Hub: an error response, a connection that failed, or a stream that ended early.
 *
 * `status` is the HTTP status, or 0 when no response arrived. `code` is the server's error code when the response
 * carries one (workflow runs: `not_paused`, `step_not_pending`, ...), else an SDK code from {@link ClientErrorCode}.
 * `details` is the server's `details` payload as sent (validation errors are a list, workflow errors an object).
 */
export class AgentHubError extends Error {
    readonly status: number;
    readonly code: string;
    readonly details: unknown;
    /** The parsed response body, when the response had one. */
    readonly body: unknown;
    declare readonly cause?: unknown;

    constructor(init: {
        message: string;
        status?: number;
        code?: string;
        details?: unknown;
        body?: unknown;
        cause?: unknown;
    }) {
        super(init.message);
        this.name = 'AgentHubError';
        this.status = init.status ?? 0;
        this.code = init.code ?? 'http_error';
        this.details = init.details;
        this.body = init.body;
        if (init.cause !== undefined) (this as { cause?: unknown }).cause = init.cause;
    }
}

export function isAgentHubError(value: unknown): value is AgentHubError {
    return value instanceof AgentHubError;
}

/** An aborted request or wait. Same shape as the platform's fetch abort so `err.name === 'AbortError'` works anywhere. */
export function abortError(signal?: AbortSignal): Error {
    const reason: unknown = signal?.reason;
    if (reason instanceof Error && reason.name === 'AbortError') return reason;
    const error = new Error('The operation was aborted');
    error.name = 'AbortError';
    if (reason !== undefined) (error as Error & { cause?: unknown }).cause = reason;
    return error;
}

export function isAbortError(value: unknown): boolean {
    return value instanceof Error && value.name === 'AbortError';
}

/**
 * Read an error response. The server answers `{ error: <code>, message, details }`; older routes answer FastAPI's
 * `{ detail: ... }` where detail is a string or `{ code, message, details }`.
 */
export async function errorFromResponse(response: Response): Promise<AgentHubError> {
    const text = await response.text().catch(() => '');
    let body: unknown = text;
    try {
        body = text ? JSON.parse(text) : undefined;
    } catch {
        // not JSON: keep the text
    }
    const record = isRecord(body) ? body : {};
    const nested = isRecord(record.detail) ? record.detail : {};
    const code = firstString(record.error, record.code, nested.error, nested.code);
    const message =
        firstString(record.message, nested.message, typeof record.detail === 'string' ? record.detail : undefined) ??
        (typeof body === 'string' && body ? body : undefined) ??
        (response.statusText || `HTTP ${response.status}`);
    const details = record.details ?? nested.details ?? (Array.isArray(record.detail) ? record.detail : undefined);
    return new AgentHubError({
        message,
        status: response.status,
        code: code ?? 'http_error',
        details,
        body,
    });
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function firstString(...values: unknown[]): string | undefined {
    return values.find((v): v is string => typeof v === 'string' && v.length > 0);
}
