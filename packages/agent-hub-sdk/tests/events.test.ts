// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { createClient, type LiveEvent, type WebSocketFactory, type WebSocketLike } from '../src';

class FakeSocket implements WebSocketLike {
    sent: Array<Record<string, unknown>> = [];
    closedWith: number | undefined;
    onopen: WebSocketLike['onopen'] = null;
    onmessage: WebSocketLike['onmessage'] = null;
    onerror: WebSocketLike['onerror'] = null;
    onclose: WebSocketLike['onclose'] = null;
    constructor(
        readonly url: string,
        readonly headers: Record<string, string>,
    ) {}
    send(data: string) {
        this.sent.push(JSON.parse(data));
    }
    close(code?: number) {
        this.closedWith = code;
    }
    // server side
    open() {
        this.onopen?.({});
    }
    say(message: unknown) {
        this.onmessage?.({ data: JSON.stringify(message) });
    }
    drop() {
        this.onclose?.({ code: 1006 });
    }
}

function setup(options: { headers?: Record<string, string> } = {}) {
    const sockets: FakeSocket[] = [];
    const webSocket: WebSocketFactory = (url, init) => {
        const socket = new FakeSocket(url, init.headers);
        sockets.push(socket);
        return socket;
    };
    const client = createClient({ baseUrl: 'http://hub.test', webSocket, headers: options.headers });
    return { client, sockets };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

const message: LiveEvent = {
    event_type: 'message',
    session_id: 's1',
    timestamp: '2026-10-28T00:00:00Z',
    data: { role: 'assistant', content: 'hi' },
};

describe('events.subscribe', () => {
    it('opens the socket with the client headers, subscribes with the filters and delivers events', async () => {
        const { client, sockets } = setup({ headers: { 'X-Agent-Hub-Owner-Token': 'tok' } });
        const handler = vi.fn();
        const sub = client.events.subscribe(handler, { sessionIds: ['s1'], eventTypes: ['message'] });
        await tick();
        const socket = sockets[0]!;
        expect(socket.url).toBe('ws://hub.test/api/events');
        expect(socket.headers).toEqual({ 'X-Agent-Hub-Owner-Token': 'tok' });
        socket.open();
        expect(socket.sent).toEqual([{ type: 'subscribe', session_ids: ['s1'], event_types: ['message'] }]);
        socket.say({ type: 'subscribed', subscription_id: 'sub-1' });
        await sub.ready;
        expect(sub.status).toBe('connected');

        socket.say(message);
        socket.say({ event_type: 'something_new', session_id: 's1', timestamp: 't', data: {} }); // unknown: skipped
        socket.say({ type: 'updated', subscription_id: 'sub-1' }); // control frames are not events
        expect(handler.mock.calls).toEqual([[message]]);
    });

    it('sends no filters when none are given, and update changes them live', async () => {
        const { client, sockets } = setup();
        const sub = client.events.subscribe(() => undefined);
        await tick();
        const socket = sockets[0]!;
        socket.open();
        expect(socket.sent[0]).toEqual({ type: 'subscribe' });
        socket.say({ type: 'subscribed' });
        sub.update({ sessionIds: ['s2'] });
        expect(socket.sent[1]).toEqual({ type: 'update', session_ids: ['s2'] });
    });

    it('reconnects after the socket drops and subscribes again with the latest filters', async () => {
        const { client, sockets } = setup();
        const statuses: string[] = [];
        const sub = client.events.subscribe(() => undefined, {
            reconnectDelayMs: 1,
            onStatus: (s) => statuses.push(s),
        });
        await tick();
        sockets[0]!.open();
        sockets[0]!.say({ type: 'subscribed' });
        sub.update({ eventTypes: ['complete'] });
        sockets[0]!.drop();
        expect(sub.status).toBe('reconnecting');
        await new Promise((r) => setTimeout(r, 20));
        expect(sockets).toHaveLength(2);
        sockets[1]!.open();
        expect(sockets[1]!.sent).toEqual([{ type: 'subscribe', event_types: ['complete'] }]);
        sockets[1]!.say({ type: 'subscribed' });
        expect(statuses).toEqual(['connected', 'reconnecting', 'connected']);
        sub.close();
    });

    it('close stops for good: closes the socket, no reconnect, ready rejects if never confirmed', async () => {
        const { client, sockets } = setup();
        const sub = client.events.subscribe(() => undefined, { reconnectDelayMs: 1 });
        await tick();
        sockets[0]!.open();
        sub.close();
        sockets[0]!.drop();
        await new Promise((r) => setTimeout(r, 15));
        expect(sockets).toHaveLength(1);
        expect(sockets[0]!.closedWith).toBe(1000);
        expect(sub.status).toBe('closed');
        await expect(sub.ready).rejects.toThrow(/closed before/);
    });

    it('passes a server error for the subscription to onError', async () => {
        const { client, sockets } = setup();
        const onError = vi.fn();
        const sub = client.events.subscribe(() => undefined, { onError });
        await tick();
        sockets[0]!.say({ type: 'error', message: 'Invalid event type: nope' });
        expect(onError).toHaveBeenCalledWith('Invalid event type: nope');
        sub.close();
    });

    it('does not reconnect when reconnect is off', async () => {
        const { client, sockets } = setup();
        const sub = client.events.subscribe(() => undefined, { reconnect: false });
        await tick();
        sockets[0]!.drop();
        await new Promise((r) => setTimeout(r, 10));
        expect(sockets).toHaveLength(1);
        expect(sub.status).toBe('closed');
    });
});
