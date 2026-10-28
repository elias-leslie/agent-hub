// @vitest-environment node
//
// Opt-in: runs against a real Agent Hub. `AGENT_HUB_LIVE=1`. Uses the free `provider-liveness-probe` agent and creates
// one short session, which it closes. The client identity comes from AGENT_HUB_CLIENT_ID / AGENT_HUB_REQUEST_SOURCE or,
// as `st` reads it, SUMMITFLOW_CLIENT_ID / SUMMITFLOW_REQUEST_SOURCE in ~/.env.local. Nothing is printed.
import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { AgentHubError, createClient, type LiveEvent } from '../src';

function envLocal(): Record<string, string> {
    try {
        const out: Record<string, string> = {};
        for (const raw of readFileSync(join(homedir(), '.env.local'), 'utf8').split('\n')) {
            const line = raw.trim().replace(/^export /, '');
            const eq = line.indexOf('=');
            if (eq > 0 && !line.startsWith('#')) out[line.slice(0, eq).trim()] = line.slice(eq + 1).trim().replace(/^['"]|['"]$/g, '');
        }
        return out;
    } catch {
        return {};
    }
}

const live = Boolean(process.env.AGENT_HUB_LIVE);
const file = live ? envLocal() : {};
const clientId = process.env.AGENT_HUB_CLIENT_ID ?? file.SUMMITFLOW_CLIENT_ID;
const requestSource = process.env.AGENT_HUB_REQUEST_SOURCE ?? file.SUMMITFLOW_REQUEST_SOURCE ?? 'agent-hub-sdk-tests';
const ownerToken = process.env.AGENT_HUB_OWNER_TOKEN;

describe.skipIf(!live)('live Agent Hub', () => {
    const hub = createClient({
        baseUrl: process.env.AGENT_HUB_URL ?? 'http://localhost:8003',
        clientId,
        requestSource,
        headers: ownerToken ? { 'X-Agent-Hub-Owner-Token': ownerToken } : undefined,
    });
    const agent = 'provider-liveness-probe';

    it('lists models and agents', async () => {
        const [models, agents] = await Promise.all([hub.models.list(), hub.agents.list()]);
        expect(models.length).toBeGreaterThan(0);
        expect(agents.map((a) => a.slug)).toContain(agent);
    });

    it('streams a turn, shows it on the live socket and in the session, then closes the session', async () => {
        const live: LiveEvent[] = [];
        const problems: string[] = [];
        const subscription = hub.events.subscribe((event) => live.push(event), { onError: (m) => problems.push(m) });
        // The events socket is owner-only: without AGENT_HUB_OWNER_TOKEN the server refuses the upgrade.
        await Promise.race([
            subscription.ready,
            new Promise((_, reject) =>
                setTimeout(() => reject(new Error(`events socket not subscribed in 10s: ${problems.join('; ') || 'no error'}`)), 10_000),
            ),
        ]).catch((error) => {
            subscription.close();
            throw error;
        });
        try {
            const events: string[] = [];
            const turn = await hub.turns.run(
                {
                    agent_slug: agent,
                    project_id: 'agent-hub',
                    use_memory: false,
                    messages: [{ role: 'user', content: 'Reply with exactly: pong' }],
                },
                { onEvent: (event) => events.push(event.type), signal: AbortSignal.timeout(120_000) },
            );
            expect(events[0]).toBe('connected');
            expect(events.at(-1)).toBe('done');
            expect(turn.status).toBe('done');
            expect(turn.content.toLowerCase()).toContain('pong');
            expect(turn.routing.agent_used).toBe(agent);
            expect(typeof turn.done?.model_used).toBe('string');
            const sessionId = turn.sessionId!;

            const session = await hub.sessions.get(sessionId);
            expect(session.id).toBe(sessionId);
            expect((await hub.sessions.messages(sessionId)).some((m) => m.role === 'user')).toBe(true);
            expect((await hub.sessions.list({ page_size: 5 })).sessions.length).toBeGreaterThan(0);
            expect((await hub.sessions.events(sessionId)).session_id).toBe(sessionId);

            await new Promise((r) => setTimeout(r, 500)); // let the socket deliver
            expect(live.some((e) => e.session_id === sessionId)).toBe(true);

            expect((await hub.sessions.close(sessionId)).id).toBe(sessionId);
        } finally {
            subscription.close();
        }
    }, 150_000);

    it('cancel of a turn that is not running is not an error', async () => {
        expect(await hub.turns.cancel('00000000-0000-0000-0000-000000000000')).toMatchObject({ cancelled: false });
    });

    it('lists workflow runs and reports a missing run as a 404 AgentHubError', async () => {
        expect((await hub.workflowRuns.list({ limit: 1 })).runs).toBeInstanceOf(Array);
        const error = await hub.workflowRuns.get('no-such-run').catch((e: unknown) => e);
        expect(error).toBeInstanceOf(AgentHubError);
        expect(error).toMatchObject({ status: 404, message: expect.any(String) });
    });
});
