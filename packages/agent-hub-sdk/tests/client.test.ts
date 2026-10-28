// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { AgentHubError, createClient, eventsUrl, OWNER_TOKEN_HEADER } from '../src';
import { jsonResponse, mockFetch } from './helpers';

describe('createClient', () => {
    it('sends the configured headers on every request and trims the base url', async () => {
        const fetch = mockFetch(() => jsonResponse({ models: [{ id: 'm1' }] }));
        const client = createClient({
            baseUrl: 'http://hub.test///',
            fetch,
            clientId: 'cid',
            requestSource: 'aico',
            headers: { [OWNER_TOKEN_HEADER]: 'secret', 'X-Request-Source': 'override' },
        });
        expect(await client.models.list()).toEqual([{ id: 'm1' }]);
        expect(fetch.requests[0]!.url).toBe('http://hub.test/api/models');
        expect(fetch.requests[0]!.headers).toMatchObject({
            'X-Client-Id': 'cid',
            'X-Request-Source': 'override', // explicit headers win over the convenience options
            [OWNER_TOKEN_HEADER]: 'secret',
        });
    });

    it('calls a headers function per request, so a rotated token is picked up', async () => {
        const fetch = mockFetch(() => jsonResponse({ agents: [], total: 0 }));
        let token = 't1';
        const client = createClient({ baseUrl: '', fetch, headers: async () => ({ [OWNER_TOKEN_HEADER]: token }) });
        await client.agents.list();
        token = 't2';
        await client.agents.list({ active_only: false, limit: 5 });
        expect(fetch.requests.map((r) => r.headers[OWNER_TOKEN_HEADER])).toEqual(['t1', 't2']);
        expect(fetch.requests[1]!.url).toBe('/api/agents?active_only=false&limit=5');
    });

    it('uses the platform fetch when none is given', async () => {
        const original = globalThis.fetch;
        const platform = vi.fn(async () => jsonResponse({ models: [] }));
        globalThis.fetch = platform as unknown as typeof fetch;
        try {
            await createClient({ baseUrl: 'http://hub.test' }).models.list();
            expect(platform).toHaveBeenCalledOnce();
        } finally {
            globalThis.fetch = original;
        }
    });

    it('reports a response that is not JSON as invalid_response', async () => {
        const fetch = mockFetch(() => new Response('<html>', { status: 200 }));
        const error = await createClient({ baseUrl: 'http://hub.test', fetch }).models.list().catch((e: unknown) => e);
        expect(error).toBeInstanceOf(AgentHubError);
        expect(error).toMatchObject({ code: 'invalid_response', status: 200 });
    });
});

describe('sessions, models, agents', () => {
    it('maps sessions calls to their routes', async () => {
        const fetch = mockFetch((req) =>
            req.method === 'GET' && req.url.endsWith('/s%201')
                ? jsonResponse({ id: 's 1', messages: [{ id: 'm1', role: 'user', content: 'hi', tokens: 1, created_at: 't' }] })
                : jsonResponse({ id: 's 1', status: 'closed', message: 'ok' }),
        );
        const { sessions } = createClient({ baseUrl: 'http://hub.test', fetch });
        await sessions.create({ project_id: 'p', provider: 'x', model: 'y' });
        await sessions.list({ project_id: 'p', page_size: 5, roots_only: true });
        await sessions.get('s 1', { includeMessages: false });
        await sessions.close('s 1');
        await sessions.events('s 1', { page_size: 50, order: 'desc' });
        expect(await sessions.messages('s 1')).toHaveLength(1);
        expect(fetch.requests.map((r) => [r.method, r.url.replace('http://hub.test', '')])).toEqual([
            ['POST', '/api/sessions'],
            ['GET', '/api/sessions?project_id=p&page_size=5&roots_only=true'],
            ['GET', '/api/sessions/s%201?include_events=false'],
            ['POST', '/api/sessions/s%201/close'],
            ['GET', '/api/sessions/s%201/events?page_size=50&order=desc'],
            ['GET', '/api/sessions/s%201'],
        ]);
    });

    it('agents.list returns the agents array', async () => {
        const fetch = mockFetch(() => jsonResponse({ agents: [{ slug: 'chat' }], total: 1 }));
        expect(await createClient({ baseUrl: 'http://hub.test', fetch }).agents.list()).toEqual([{ slug: 'chat' }]);
    });
});

describe('eventsUrl', () => {
    it('swaps http for ws and https for wss', () => {
        expect(eventsUrl('http://hub.test:8003')).toBe('ws://hub.test:8003/api/events');
        expect(eventsUrl('https://hub.test')).toBe('wss://hub.test/api/events');
    });

    it('needs an absolute base outside a browser', () => {
        expect(() => eventsUrl('')).toThrow(/absolute/);
    });
});
