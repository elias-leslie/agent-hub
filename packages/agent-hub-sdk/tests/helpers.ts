import type { FetchLike } from '../src';

const encoder = new TextEncoder();

/** A streaming `text/event-stream` response that delivers `chunks` one read at a time. */
export function sseResponse(
    chunks: Array<string | Uint8Array>,
    options: { status?: number; onCancel?: () => void; hang?: boolean; signal?: AbortSignal | null } = {},
): Response {
    let index = 0;
    const body = new ReadableStream<Uint8Array>({
        start(controller) {
            // A real fetch body errors when its request is aborted.
            options.signal?.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')));
        },
        async pull(controller) {
            if (index < chunks.length) {
                const chunk = chunks[index++]!;
                controller.enqueue(typeof chunk === 'string' ? encoder.encode(chunk) : chunk);
                return;
            }
            if (options.hang) await new Promise(() => undefined); // an open connection with nothing more to say
            controller.close();
        },
        cancel() {
            options.onCancel?.();
        },
    });
    return new Response(body, {
        status: options.status ?? 200,
        headers: { 'Content-Type': 'text/event-stream' },
    });
}

export function jsonResponse(body: unknown, status = 200): Response {
    return new Response(status === 204 ? null : JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });
}

/** Cut `text` into pieces of `size` characters (splits lines, events and surrogate pairs anywhere). */
export function slices(text: string, size: number): string[] {
    const out: string[] = [];
    for (let i = 0; i < text.length; i += size) out.push(text.slice(i, i + size));
    return out;
}

/** The same text as raw bytes cut every `size` bytes, so multi-byte characters split across reads. */
export function byteSlices(text: string, size: number): Uint8Array[] {
    const bytes = encoder.encode(text);
    const out: Uint8Array[] = [];
    for (let i = 0; i < bytes.length; i += size) out.push(bytes.slice(i, i + size));
    return out;
}

export interface RecordedRequest {
    url: string;
    method: string;
    headers: Record<string, string>;
    body: unknown;
    signal?: AbortSignal | null;
}

/** A `fetch` answering from `respond` in order or by function, recording what it was asked. */
export function mockFetch(
    respond: Response | Array<Response | Error> | ((request: RecordedRequest, call: number) => Response | Promise<Response>),
): FetchLike & { requests: RecordedRequest[] } {
    const requests: RecordedRequest[] = [];
    const fn = async (url: string, init: RequestInit = {}) => {
        const request: RecordedRequest = {
            url,
            method: init.method ?? 'GET',
            headers: { ...(init.headers as Record<string, string> | undefined) },
            body: typeof init.body === 'string' ? JSON.parse(init.body) : undefined,
            signal: init.signal,
        };
        requests.push(request);
        const call = requests.length - 1;
        if (typeof respond === 'function') return respond(request, call);
        const next = Array.isArray(respond) ? respond[Math.min(call, respond.length - 1)]! : respond;
        if (next instanceof Error) throw next;
        return next;
    };
    return Object.assign(fn, { requests });
}

export async function collect<T>(iterable: AsyncIterable<T>): Promise<T[]> {
    const out: T[] = [];
    for await (const item of iterable) out.push(item);
    return out;
}
