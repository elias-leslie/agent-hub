import { abortError, AgentHubError, errorFromResponse, isAbortError } from './errors';

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export type HeaderSource =
    | Record<string, string>
    | (() => Record<string, string> | Promise<Record<string, string>>);

export interface Transport {
    readonly baseUrl: string;
    /** Resolved headers for every request (the client's `headers`, evaluated now). */
    headers(): Promise<Record<string, string>>;
    /** A response that is ok, or an {@link AgentHubError}. Aborts reject with an `AbortError`. */
    send(method: string, path: string, init?: SendInit): Promise<Response>;
    json<T>(method: string, path: string, init?: SendInit): Promise<T>;
}

export interface SendInit {
    query?: object;
    body?: unknown;
    signal?: AbortSignal;
    headers?: Record<string, string>;
}

export function createTransport(options: {
    baseUrl: string;
    fetch?: FetchLike;
    headers?: HeaderSource;
}): Transport {
    const baseUrl = options.baseUrl.replace(/\/+$/, '');
    // Called through globalThis so a detached browser `fetch` does not throw "Illegal invocation".
    const doFetch: FetchLike = options.fetch ?? ((input, init) => globalThis.fetch(input, init));

    async function headers(): Promise<Record<string, string>> {
        const source = options.headers;
        return (typeof source === 'function' ? await source() : source) ?? {};
    }

    async function send(method: string, path: string, init: SendInit = {}): Promise<Response> {
        const hasBody = init.body !== undefined;
        const requestHeaders: Record<string, string> = {
            Accept: 'application/json',
            ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
            ...(await headers()),
            ...init.headers,
        };
        let response: Response;
        try {
            response = await doFetch(baseUrl + path + queryString(init.query), {
                method,
                headers: requestHeaders,
                body: hasBody ? JSON.stringify(init.body) : undefined,
                signal: init.signal,
            });
        } catch (error) {
            if (init.signal?.aborted || isAbortError(error)) throw abortError(init.signal);
            throw new AgentHubError({
                message: `Cannot reach Agent Hub: ${error instanceof Error ? error.message : String(error)}`,
                code: 'network_error',
                cause: error,
            });
        }
        if (!response.ok) throw await errorFromResponse(response);
        return response;
    }

    async function json<T>(method: string, path: string, init?: SendInit): Promise<T> {
        const response = await send(method, path, init);
        if (response.status === 204) return undefined as T;
        const text = await response.text();
        if (!text) return undefined as T;
        try {
            return JSON.parse(text) as T;
        } catch (cause) {
            throw new AgentHubError({
                message: 'Agent Hub returned a response that is not JSON',
                status: response.status,
                code: 'invalid_response',
                body: text.slice(0, 500),
                cause,
            });
        }
    }

    return { baseUrl, headers, send, json };
}

/** `?a=1&b=2` from the defined values; arrays repeat the key. Empty when nothing is set. */
export function queryString(query: object | undefined): string {
    if (!query) return '';
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
        if (value === undefined || value === null) continue;
        for (const item of Array.isArray(value) ? value : [value]) params.append(key, String(item));
    }
    const text = params.toString();
    return text ? `?${text}` : '';
}

export function pathSegment(value: string): string {
    return encodeURIComponent(value);
}

/** Resolve after `ms`, or reject with an `AbortError` as soon as `signal` aborts. */
export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        if (signal?.aborted) return reject(abortError(signal));
        const onAbort = () => {
            clearTimeout(timer);
            reject(abortError(signal));
        };
        const timer = setTimeout(() => {
            signal?.removeEventListener('abort', onAbort);
            resolve();
        }, ms);
        signal?.addEventListener('abort', onAbort, { once: true });
    });
}
