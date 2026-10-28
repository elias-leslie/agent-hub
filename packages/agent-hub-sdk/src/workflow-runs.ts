import { abortError, AgentHubError, isAbortError } from './errors';
import { pathSegment, sleep as defaultSleep, type Transport } from './http';
import type {
    AddStepsRequest,
    CancelOptions,
    CreatedRun,
    ListRunsParams,
    OwnerDecision,
    RemoveStepRequest,
    RevisionResult,
    RunAction,
    RunDefinition,
    RunList,
    RunRevision,
    RunView,
    StepRevision,
} from './types/workflow';
import {
    diffSnapshots,
    endOfWait,
    parseUntil,
    snapshotRun,
    snapshotsEqual,
    type WaitOutcome,
    type WaitUntil,
} from './workflow-wait';

interface CallOptions {
    signal?: AbortSignal;
}

export interface WaitOptions {
    /** Ends the wait with an `AbortError`. There is no other time limit, and aborting cancels nothing on the run. */
    signal?: AbortSignal;
    /** Poll interval after a change, in ms. Default 2000. */
    pollMinMs?: number;
    /** The interval grows 1.5x per quiet poll up to this. Default 10000. */
    pollMaxMs?: number;
    /** Failed reads in a row before giving up with code `lost_contact`. Default 12. */
    maxConsecutiveErrors?: number;
    /** Called with the plain lines describing each change seen (see `st workflow wait`), and the run then. */
    onChange?: (lines: string[], run: RunView) => void;
    /** Replace the wait between polls (tests). Must reject with an `AbortError` when `signal` aborts. */
    sleep?: (ms: number, signal?: AbortSignal) => Promise<void>;
}

export interface WaitResult {
    outcome: WaitOutcome;
    /** Plain words for why it ended, e.g. `run needs_owner` or `step build failed`. */
    reason: string;
    /** The run as last read. */
    run: RunView;
    /** Every change line seen while waiting. */
    changes: string[];
}

export interface WorkflowRunsApi {
    /** Create and start a run. Idempotent on `request_id`: the same id returns the existing run with `created: false`. */
    create(definition: RunDefinition, options?: CallOptions): Promise<CreatedRun>;
    list(params?: ListRunsParams, options?: CallOptions): Promise<RunList>;
    get(id: string, options?: CallOptions): Promise<RunView>;
    /** Change a run-level setting of a run that is going on (`max_concurrent_steps`). */
    revise(id: string, change: RunRevision, options?: CallOptions): Promise<RevisionResult>;
    /** Add steps; reopens a completed run. */
    addSteps(id: string, request: AddStepsRequest, options?: CallOptions): Promise<RevisionResult>;
    /** Change a pending step. Fails with `step_not_pending` once it has started. */
    reviseStep(id: string, stepKey: string, change: StepRevision, options?: CallOptions): Promise<RevisionResult>;
    /** Remove a pending step nothing depends on, or revise its dependents in the same call. */
    removeStep(id: string, stepKey: string, request?: RemoveStepRequest, options?: CallOptions): Promise<RevisionResult>;
    /** Stop the whole run. Asking again while it stops returns the same state. */
    cancel(id: string, cancel?: CancelOptions, options?: CallOptions): Promise<RunAction>;
    /** Stop one step; the run carries on with its other steps. */
    cancelStep(id: string, stepKey: string, cancel?: CancelOptions, options?: CallOptions): Promise<RunAction>;
    /** Resolve a run paused for the owner: retry, skip or fail the waiting step. */
    resume(id: string, decision: OwnerDecision, options?: CallOptions): Promise<RunAction>;
    /**
     * Poll the run until `until` holds and return how it ended. Same outcomes as `st workflow wait`:
     * `completed`, `failed`, `cancelled`, `needs_owner` (any entry in the pause's `waiting` map; a usage-limit wait
     * that clears itself does not count), `step_done`, `step_ended`, `changed`.
     *
     * The first read is strict (a missing run rejects at once). After that a failed read (network, 5xx, 429) is
     * retried with backoff, and `maxConsecutiveErrors` of them in a row reject with code `lost_contact`; the run
     * itself is held by the runner and can be waited on again. Rejects with `AbortError` when `signal` aborts, and
     * with code `step_not_in_run` when `step:<key>` names a step the finished run does not have.
     */
    waitFor(id: string, until: WaitUntil, options?: WaitOptions): Promise<WaitResult>;
}

export function createWorkflowRunsApi(transport: Transport): WorkflowRunsApi {
    const run = (id: string) => `/api/workflow-runs/${pathSegment(id)}`;
    const step = (id: string, key: string) => `${run(id)}/steps/${pathSegment(key)}`;
    const cancelBody = (cancel?: CancelOptions) => (cancel?.reason ? { reason: cancel.reason } : undefined);

    const api: WorkflowRunsApi = {
        create: (definition, options) =>
            transport.json('POST', '/api/workflow-runs', { body: definition, signal: options?.signal }),
        list: (params, options) =>
            transport.json('GET', '/api/workflow-runs', { query: params, signal: options?.signal }),
        get: (id, options) => transport.json('GET', run(id), { signal: options?.signal }),
        revise: (id, change, options) =>
            transport.json('PATCH', run(id), { body: change, signal: options?.signal }),
        addSteps: (id, request, options) =>
            transport.json('POST', `${run(id)}/steps`, { body: request, signal: options?.signal }),
        reviseStep: (id, key, change, options) =>
            transport.json('PATCH', step(id, key), { body: change, signal: options?.signal }),
        removeStep: (id, key, request, options) =>
            transport.json('DELETE', step(id, key), { body: request, signal: options?.signal }),
        cancel: (id, cancel, options) =>
            transport.json('POST', `${run(id)}/cancel`, { body: cancelBody(cancel), signal: options?.signal }),
        cancelStep: (id, key, cancel, options) =>
            transport.json('POST', `${step(id, key)}/cancel`, {
                body: cancelBody(cancel),
                signal: options?.signal,
            }),
        resume: (id, decision, options) =>
            transport.json('POST', `${run(id)}/resume`, { body: decision, signal: options?.signal }),

        async waitFor(id, until, options = {}) {
            const target = parseUntil(until);
            const { signal } = options;
            const pollMin = options.pollMinMs ?? 2000;
            const pollMax = options.pollMaxMs ?? 10000;
            const maxErrors = options.maxConsecutiveErrors ?? 12;
            const wait = options.sleep ?? defaultSleep;
            const changes: string[] = [];

            if (signal?.aborted) throw abortError(signal);
            let view = await api.get(id, { signal }); // strict: a missing run or bad address fails right away
            let seen = snapshotRun(view);
            const baseline = target.kind === 'any-change' ? seen : null;
            let interval = pollMin;
            let errors = 0;

            while (true) {
                const end = endOfWait(target, view, baseline);
                if (end.over) {
                    if ('error' in end) {
                        throw new AgentHubError({ message: end.reason, code: end.error, details: { run: view } });
                    }
                    return { outcome: end.outcome, reason: end.reason, run: view, changes };
                }
                await wait(interval, signal);
                try {
                    view = await api.get(id, { signal });
                    errors = 0;
                } catch (error) {
                    if (signal?.aborted || isAbortError(error)) throw abortError(signal);
                    if (!(error instanceof AgentHubError) || !readRetryable(error)) throw error;
                    errors += 1;
                    if (errors >= maxErrors) {
                        throw new AgentHubError({
                            message: `Lost contact with Agent Hub after ${errors} failed reads; the run is held by the runner and can be waited on again`,
                            code: 'lost_contact',
                            cause: error,
                        });
                    }
                    interval = Math.min(interval * 1.5, pollMax);
                    continue;
                }
                const current = snapshotRun(view);
                if (!snapshotsEqual(seen, current)) {
                    const lines = diffSnapshots(seen, current);
                    changes.push(...lines);
                    options.onChange?.(lines, view);
                    seen = current;
                    interval = pollMin;
                } else {
                    interval = Math.min(interval * 1.5, pollMax);
                }
            }
        },
    };
    return api;
}

function readRetryable(error: AgentHubError): boolean {
    return error.code === 'network_error' || error.status >= 500 || error.status === 429;
}
