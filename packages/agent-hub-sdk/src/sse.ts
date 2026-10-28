/**
 * Incremental Server-Sent Events parser.
 *
 * Feed it text as it arrives (chunks may split a line, an event or a UTF-8 character anywhere); it returns the
 * `data` payload of every event completed by that chunk. Handles `\n`, `\r\n` and `\r` line ends, comment lines
 * (`: keepalive`), multi-line `data:` fields, and ignores `event:`, `id:` and `retry:` (Agent Hub's events carry their
 * own `type` and `seq` inside the JSON).
 */
export class SseParser {
    private buffer = '';
    private data: string[] = [];
    private sawCr = false;

    /** Data payloads of the events finished by `text`, in order. */
    push(text: string): string[] {
        const out: string[] = [];
        if (text === '') return out;
        // A "\r" at the end of the last chunk may be the first half of "\r\n"; skip the "\n" that follows it.
        if (this.sawCr && text.startsWith('\n')) text = text.slice(1);
        this.sawCr = text.endsWith('\r');
        this.buffer += text;
        let start = 0;
        for (let i = 0; i < this.buffer.length; i++) {
            const char = this.buffer[i];
            if (char !== '\n' && char !== '\r') continue;
            this.line(this.buffer.slice(start, i), out);
            if (char === '\r' && this.buffer[i + 1] === '\n') i++;
            start = i + 1;
        }
        this.buffer = this.buffer.slice(start);
        return out;
    }

    /**
     * End of stream: a final line without a newline, and an event that was never closed by a blank line, are
     * delivered (Agent Hub always closes events, so this only matters for a proxy that cut the last one short).
     */
    flush(): string[] {
        const out: string[] = [];
        if (this.buffer) this.line(this.buffer, out);
        this.buffer = '';
        this.dispatch(out);
        return out;
    }

    private line(line: string, out: string[]): void {
        if (line === '') return this.dispatch(out);
        if (line.startsWith(':')) return;
        const colon = line.indexOf(':');
        const field = colon === -1 ? line : line.slice(0, colon);
        if (field !== 'data') return;
        let value = colon === -1 ? '' : line.slice(colon + 1);
        if (value.startsWith(' ')) value = value.slice(1);
        this.data.push(value);
    }

    private dispatch(out: string[]): void {
        if (this.data.length) out.push(this.data.join('\n'));
        this.data = [];
    }
}

/** Read a response body as decoded text chunks. Works for web streams (browsers, Electron, Node fetch) and async iterables. */
export async function* readTextChunks(
    body: ReadableStream<Uint8Array> | AsyncIterable<Uint8Array | string>,
    onClose?: () => void,
): AsyncGenerator<string> {
    const decoder = new TextDecoder();
    try {
        if ('getReader' in body) {
            const reader = body.getReader();
            try {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    yield decoder.decode(value, { stream: true });
                }
            } finally {
                // Closes the connection when the caller stops early; harmless when the stream already ended.
                await reader.cancel().catch(() => undefined);
            }
        } else {
            for await (const chunk of body) {
                yield typeof chunk === 'string' ? chunk : decoder.decode(chunk, { stream: true });
            }
        }
        const rest = decoder.decode();
        if (rest) yield rest;
    } finally {
        onClose?.();
    }
}
