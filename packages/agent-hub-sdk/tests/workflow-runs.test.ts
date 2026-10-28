// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import {
    AgentHubError,
    createClient,
    diffSnapshots,
    isAbortError,
    needsDecision,
    pauseText,
    snapshotRun,
    type RunView,
    type StepView,
} from '../src';
import { jsonResponse, mockFetch, type RecordedRequest } from './helpers';

function step(key: string, status: string, extra: Partial<StepView> = {}): StepView {
    return { key, status, attempts: status === 'pending' ? 0 : 1, attempt_limit: 3, ...extra };
}

function run(state: string, steps: StepView[], extra: Partial<RunView> = {}): RunView {
    return { id: 'run-1', state, goal: 'g', plan_revision: 0, steps, ...extra };
}

/** A client whose run reads come from `views` in order (the last one repeats); an Error entry fails that read. */
function scripted(views: Array<RunView | Error | Response>) {
    const fetch = mockFetch((_req, call) => {
        const next = views[Math.min(call, views.length - 1)]!;
        if (next instanceof Error) throw next;
        return next instanceof Response ? next : jsonResponse(next);
    });
    const client = createClient({ baseUrl: 'http://hub.test', fetch });
    const sleeps: number[] = [];
    const sleep = async (ms: number, signal?: AbortSignal) => {
        if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
        sleeps.push(ms);
    };
    const wait = (until: Parameters<typeof client.workflowRuns.waitFor>[1], extra = {}) =>
        client.workflowRuns.waitFor('run-1', until, { sleep, ...extra });
    return { client, fetch, sleeps, wait };
}

describe('waitFor outcomes (the st workflow wait exits)', () => {
    it.each([
        ['completed', 'completed'],
        ['failed', 'failed'],
        ['cancelled', 'cancelled'],
    ])('done ends when the run is %s', async (state: string, outcome: string) => {
        const { wait, fetch, sleeps } = scripted([
            run('running', [step('a', 'running')]),
            run('running', [step('a', 'running')]),
            run(state, [step('a', 'completed')]),
        ]);
        const result = await wait('done');
        expect(result.outcome).toBe(outcome);
        expect(result.run.state).toBe(state);
        expect(fetch.requests).toHaveLength(3);
        expect(sleeps).toHaveLength(2);
    });

    it('returns at once when the run already ended', async () => {
        const { wait, sleeps } = scripted([run('completed', [step('a', 'completed')])]);
        expect((await wait('done')).outcome).toBe('completed');
        expect(sleeps).toHaveLength(0);
    });

    it('needs_owner when the pause reason needs a decision', async () => {
        const paused = run('needs_owner', [step('a', 'needs_owner')], {
            pause: { reason: 'chain_exhausted', step: 'a' },
        });
        const { wait } = scripted([run('running', [step('a', 'running')]), paused]);
        const result = await wait('needs_owner');
        expect(result.outcome).toBe('needs_owner');
        expect(result.run.pause?.reason).toBe('chain_exhausted');
        // done stops at a pause too
        expect((await scripted([paused]).wait('done')).outcome).toBe('needs_owner');
    });

    it('needs_owner counts any entry of the pause waiting map, not only the top-level reason', async () => {
        const paused = run('needs_owner', [step('a', 'needs_owner'), step('b', 'needs_owner')], {
            pause: {
                reason: 'usage_limit_wait',
                waiting: { a: { reason: 'usage_limit_wait' }, b: { reason: 'attempts_exhausted' } },
            },
        });
        expect(needsDecision(paused)).toBe(true);
        expect((await scripted([paused]).wait('needs_owner')).outcome).toBe('needs_owner');
    });

    it('a usage-limit wait that clears itself is not a decision for the owner', async () => {
        const waiting = run('needs_owner', [step('a', 'needs_owner')], {
            pause: { reason: 'usage_limit_wait', waiting: { a: { reason: 'usage_limit_wait' } } },
        });
        expect(needsDecision(waiting)).toBe(false);
        const { wait } = scripted([waiting, waiting, run('completed', [step('a', 'completed')])]);
        expect((await wait('needs_owner')).outcome).toBe('completed');
    });

    it('step:<key> ends done when the step completes or is skipped, ended when it fails or is refused', async () => {
        for (const status of ['completed', 'skipped']) {
            const { wait } = scripted([
                run('running', [step('a', 'running'), step('b', 'pending')]),
                run('running', [step('a', status), step('b', 'running')]),
            ]);
            const result = await wait('step:a');
            expect(result.outcome).toBe('step_done');
            expect(result.reason).toBe(`step a ${status}`);
        }
        for (const status of ['failed', 'refused', 'cancelled']) {
            const { wait } = scripted([
                run('running', [step('a', 'running')]),
                run('running', [step('a', status)]),
            ]);
            expect((await wait('step:a')).outcome).toBe('step_ended');
        }
    });

    it('step:<key> still stops when the whole run needs the owner or ends first', async () => {
        const paused = run('needs_owner', [step('a', 'completed'), step('b', 'needs_owner')], {
            pause: { reason: 'chain_exhausted' },
        });
        expect((await scripted([paused]).wait('step:b')).outcome).toBe('needs_owner');
        const failed = run('failed', [step('a', 'failed'), step('b', 'pending')]);
        expect((await scripted([failed]).wait('step:b')).outcome).toBe('failed');
    });

    it('step:<key> rejects with step_not_in_run when the run finished without that step', async () => {
        const error = await scripted([run('completed', [step('a', 'completed')])]).wait('step:nope').catch((e: unknown) => e);
        expect(error).toBeInstanceOf(AgentHubError);
        expect(error).toMatchObject({ code: 'step_not_in_run', message: 'step nope is not in this run' });
    });

    it('any-change ends on the first difference from the first read, with the change lines', async () => {
        const { wait } = scripted([
            run('running', [step('a', 'running')]),
            run('running', [step('a', 'running')], { last_activity_at: 'later' }), // activity time is not a change
            run('running', [step('a', 'completed'), step('b', 'running')], { plan_revision: 1 }),
        ]);
        const onChange = vi.fn();
        const result = await wait('any-change', { onChange });
        expect(result.outcome).toBe('changed');
        expect(result.changes).toEqual([
            'plan: revision 0 → 1',
            'step a: running → completed',
            'step b: added (running)',
        ]);
        expect(onChange).toHaveBeenCalledTimes(1);
    });

    it('any-change reports a run that ended as a change, as st workflow wait does', async () => {
        const { wait } = scripted([run('running', [step('a', 'running')]), run('completed', [step('a', 'completed')])]);
        const result = await wait('any-change');
        expect(result.outcome).toBe('changed');
        expect(result.run.state).toBe('completed');
    });

    it('rejects an until it does not know', async () => {
        const { wait } = scripted([run('running', [])]);
        await expect(wait('later' as 'done')).rejects.toThrow(TypeError);
        await expect(wait('step:' as 'done')).rejects.toThrow(TypeError);
    });
});

describe('waitFor polling', () => {
    it('backs off while quiet and goes back to the short interval after a change', async () => {
        const quiet = run('running', [step('a', 'running')]);
        const moved = run('running', [step('a', 'running', { attempts: 2 })]);
        const { wait, sleeps } = scripted([
            quiet,
            quiet,
            quiet,
            quiet,
            moved,
            moved,
            run('completed', [step('a', 'completed')]),
        ]);
        await wait('done', { pollMinMs: 100, pollMaxMs: 200 });
        // 100, then x1.5 up to the cap, back to 100 on the change at read 5, then quiet again
        expect(sleeps).toEqual([100, 150, 200, 200, 100, 150]);
    });

    it('reports each change to onChange with plain lines', async () => {
        const { wait } = scripted([
            run('running', [step('a', 'running')]),
            run('running', [step('a', 'running', { attempts: 2 })]),
            run('needs_owner', [step('a', 'needs_owner', { attempts: 2 })], { pause: { reason: 'chain_exhausted', step: 'a' } }),
        ]);
        const lines: string[][] = [];
        await wait('needs_owner', { onChange: (l: string[]) => lines.push(l) });
        expect(lines).toEqual([
            ['step a: attempt 2'],
            ['run: running → needs_owner (chain_exhausted step=a)', 'step a: running → needs_owner'],
        ]);
    });

    it('the first read is strict: a missing run rejects at once', async () => {
        const { wait, fetch } = scripted([
            jsonResponse({ error: 'not_found', message: 'run not found', details: {} }, 404),
        ]);
        await expect(wait('done')).rejects.toMatchObject({ status: 404, code: 'not_found' });
        expect(fetch.requests).toHaveLength(1);
    });

    it('rides out failed reads, then gives up as lost_contact after maxConsecutiveErrors', async () => {
        const quiet = run('running', [step('a', 'running')]);
        const blip = scripted([quiet, new TypeError('fetch failed'), jsonResponse({ error: 'x', message: 'x' }, 503), run('completed', [])]);
        expect((await blip.wait('done')).outcome).toBe('completed');

        const down = scripted([quiet, new TypeError('fetch failed')]);
        const error = await down.wait('done', { maxConsecutiveErrors: 3 }).catch((e: unknown) => e);
        expect(error).toMatchObject({ code: 'lost_contact' });
        expect(down.fetch.requests).toHaveLength(4); // the strict first read + 3 failures
    });

    it('a 4xx during the wait is not retried', async () => {
        const quiet = run('running', [step('a', 'running')]);
        const { wait } = scripted([quiet, jsonResponse({ error: 'not_found', message: 'gone' }, 404)]);
        await expect(wait('done')).rejects.toMatchObject({ status: 404 });
    });

    it('has no time limit of its own: only the signal ends it', async () => {
        const quiet = run('running', [step('a', 'running')]);
        const controller = new AbortController();
        const fetch = mockFetch(() => jsonResponse(quiet));
        const client = createClient({ baseUrl: 'http://hub.test', fetch });
        let polls = 0;
        const result = client.workflowRuns.waitFor('run-1', 'done', {
            signal: controller.signal,
            sleep: async (_ms, signal) => {
                if (++polls === 500) controller.abort();
                if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
            },
        });
        const error = await result.catch((e: unknown) => e);
        expect(isAbortError(error)).toBe(true);
        expect(polls).toBe(500);
        expect(fetch.requests.length).toBe(500); // first read + 499 polls; the 500th sleep was cut short
    });

    it('stops with AbortError while sleeping between polls, using the real sleep', async () => {
        const fetch = mockFetch(() => jsonResponse(run('running', [step('a', 'running')])));
        const client = createClient({ baseUrl: 'http://hub.test', fetch });
        const controller = new AbortController();
        const waiting = client.workflowRuns.waitFor('run-1', 'done', { signal: controller.signal, pollMinMs: 60_000 });
        await new Promise((r) => setTimeout(r, 10));
        controller.abort();
        expect(isAbortError(await waiting.catch((e: unknown) => e))).toBe(true);
    });
});

describe('snapshot and diff (ported from workflow_wait.py)', () => {
    it('describes model changes, fallbacks and failures like st workflow wait', () => {
        const before = run('running', [step('build', 'running', { chain: ['m/a'], chosen_model: 'm/a' })]);
        const after = run('running', [
            step('build', 'failed', {
                outcome: { reason: 'acceptance_failed', error: 'tests failed' },
                attempt_history: [
                    {
                        attempt: 1,
                        requested_model: 'prov/Model-A-2026-01-02',
                        served_model: 'other/model-b',
                        fallback_used: true,
                        fallback_reason: 'usage_limit',
                    },
                ],
            }),
        ]);
        expect(diffSnapshots(snapshotRun(before), snapshotRun(after))).toEqual([
            expect.stringMatching(
                /^step build: running → failed, model prov\/Model-A-2026-01-02→other\/model-b, fallback\(usage_limit\) acceptance_failed error="tests failed"$/,
            ),
        ]);
    });

    it('treats a dated snapshot of the same model as the same model', () => {
        const same = run('running', [
            step('a', 'completed', {
                attempt_history: [{ attempt: 1, requested_model: 'p/Model-X', served_model: 'model-x-2026-01-02' }],
            }),
        ]);
        expect(snapshotRun(same).steps.get('a')?.model).toBe('model-x-2026-01-02');
        expect(snapshotRun(same).steps.get('a')?.model).not.toContain('→');
    });

    it('lists removed steps, a run cancel in progress and a changed pause', () => {
        const a = snapshotRun(run('needs_owner', [step('x', 'pending'), step('y', 'pending')], { pause: { reason: 'r1' } }));
        const b = snapshotRun(run('needs_owner', [step('x', 'pending')], { pause: { reason: 'r2' }, cancelling: true }));
        expect(diffSnapshots(a, b)).toEqual(['run: pause r1 → r2', 'run: cancelling', 'step y: removed']);
    });

    it('formats a pause with its detail and every waiting step', () => {
        expect(
            pauseText({
                reason: 'chain_exhausted',
                step: 'a',
                at: 't',
                empty: [],
                waiting: { a: { reason: 'chain_exhausted' }, b: { reason: 'attempt_limit' } },
            }),
        ).toBe('chain_exhausted step=a | waiting: a (chain_exhausted), b (attempt_limit)');
        expect(pauseText(null)).toBeNull();
    });
});

describe('workflowRuns requests', () => {
    function api() {
        const fetch = mockFetch(() => jsonResponse({ ok: true, state: 'running', run_id: 'run 1' }));
        return { runs: createClient({ baseUrl: 'http://hub.test', fetch }).workflowRuns, fetch };
    }
    const sent = (r: RecordedRequest) => [r.method, r.url.replace('http://hub.test', ''), r.body];

    it('maps every method to its route', async () => {
        const { runs, fetch } = api();
        const definition = { goal: 'g', project_id: 'p', steps: [{ key: 'a', instructions: 'do', agent_slug: 'worker' }] };
        await runs.create(definition);
        await runs.list({ limit: 10, offset: 20 });
        await runs.get('run 1');
        await runs.revise('run 1', { max_concurrent_steps: 2 });
        await runs.addSteps('run 1', { steps: definition.steps, after: 'a' });
        await runs.reviseStep('run 1', 'a/b', { instructions: 'new' });
        await runs.removeStep('run 1', 'a', { revise: { b: { depends_on: [] } } });
        await runs.removeStep('run 1', 'a');
        await runs.cancel('run 1', { reason: 'stop' });
        await runs.cancel('run 1');
        await runs.cancelStep('run 1', 'a', { reason: 'why' });
        await runs.resume('run 1', { action: 'retry', step_key: 'a', model: 'm', extra_attempts: 2 });
        expect(fetch.requests.map(sent)).toEqual([
            ['POST', '/api/workflow-runs', definition],
            ['GET', '/api/workflow-runs?limit=10&offset=20', undefined],
            ['GET', '/api/workflow-runs/run%201', undefined],
            ['PATCH', '/api/workflow-runs/run%201', { max_concurrent_steps: 2 }],
            ['POST', '/api/workflow-runs/run%201/steps', { steps: definition.steps, after: 'a' }],
            ['PATCH', '/api/workflow-runs/run%201/steps/a%2Fb', { instructions: 'new' }],
            ['DELETE', '/api/workflow-runs/run%201/steps/a', { revise: { b: { depends_on: [] } } }],
            ['DELETE', '/api/workflow-runs/run%201/steps/a', undefined],
            ['POST', '/api/workflow-runs/run%201/cancel', { reason: 'stop' }],
            ['POST', '/api/workflow-runs/run%201/cancel', undefined],
            ['POST', '/api/workflow-runs/run%201/steps/a/cancel', { reason: 'why' }],
            ['POST', '/api/workflow-runs/run%201/resume', { action: 'retry', step_key: 'a', model: 'm', extra_attempts: 2 }],
        ]);
    });

    it('surfaces the backend error code and details as an AgentHubError', async () => {
        const fetch = mockFetch(
            jsonResponse(
                { error: 'step_not_pending', message: "step 'a' has started", details: { step: 'a', status: 'running' } },
                409,
            ),
        );
        const runs = createClient({ baseUrl: 'http://hub.test', fetch }).workflowRuns;
        const error = await runs.reviseStep('run-1', 'a', { instructions: 'x' }).catch((e: unknown) => e);
        expect(error).toBeInstanceOf(AgentHubError);
        expect(error).toMatchObject({
            status: 409,
            code: 'step_not_pending',
            message: "step 'a' has started",
            details: { step: 'a', status: 'running' },
        });
    });

    it('resolves a run paused for the owner end to end', async () => {
        const paused = run('needs_owner', [step('a', 'needs_owner')], { pause: { reason: 'chain_exhausted', step: 'a' } });
        const fetch = mockFetch((req) =>
            req.method === 'POST' ? jsonResponse({ run_id: 'run-1', state: 'running' }) : jsonResponse(paused),
        );
        const runs = createClient({ baseUrl: 'http://hub.test', fetch }).workflowRuns;
        const result = await runs.waitFor('run-1', 'needs_owner');
        expect(result.outcome).toBe('needs_owner');
        expect(await runs.resume('run-1', { action: 'retry', step_key: 'a' })).toMatchObject({ state: 'running' });
    });
});
