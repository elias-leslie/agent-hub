/**
 * Waiting on a workflow run: what changed between two reads of its view, and when a wait is over. A port of
 * `packages/st-cli/agent_hub_st/workflow_wait.py` (`snapshot`, `diff`, `needs_decision`, `end_code`) with the same
 * rules, so `waitFor` ends exactly where `st workflow wait` exits.
 */

import type { PauseEntry, RunView, StepView } from './types/workflow';

export const FINISHED_RUN_STATES = ['completed', 'failed', 'cancelled'] as const;
/** Step statuses that end a step for good (a step that is `needs_owner` or `pending` can still move). */
export const FINISHED_STEP_STATUSES = ['completed', 'skipped', 'cancelled', 'failed', 'refused'] as const;
/** A pause the runner clears by itself when a usage limit resets: nothing for the owner to decide. */
export const SELF_RESUMING_PAUSES = ['usage_limit_wait'] as const;

/** What to wait for: the run ending or pausing for the owner (`done`), only the pause, any change, or one step. */
export type WaitUntil = 'done' | 'needs_owner' | 'any-change' | `step:${string}`;

/**
 * How a wait ended. Mirrors the `st workflow wait` exit codes: `completed` 0, `needs_owner` 10, `failed` 11,
 * `cancelled` 12, `step_ended` 13, `step_done` 20, `changed` 21.
 */
export type WaitOutcome =
    | 'completed'
    | 'needs_owner'
    | 'failed'
    | 'cancelled'
    | 'step_done'
    | 'step_ended'
    | 'changed';

export function parseUntil(until: string): { kind: 'done' | 'needs_owner' | 'any-change' | 'step'; key?: string } {
    if (until === 'done' || until === 'needs_owner' || until === 'any-change') return { kind: until };
    if (until.startsWith('step:') && until.length > 5) return { kind: 'step', key: until.slice(5) };
    throw new TypeError('until must be done, needs_owner, any-change or step:<key>');
}

function isFinishedRun(state: unknown): boolean {
    return (FINISHED_RUN_STATES as readonly unknown[]).includes(state);
}

function isFinishedStep(status: unknown): boolean {
    return (FINISHED_STEP_STATUSES as readonly unknown[]).includes(status);
}

/** Whether any pause reason needs the owner: the top-level one and every entry of the `waiting` map. */
export function needsDecision(run: RunView): boolean {
    if (run.state !== 'needs_owner') return false;
    const pause = run.pause ?? {};
    const reasons: unknown[] = [pause.reason];
    for (const entry of Object.values(pause.waiting ?? {})) reasons.push((entry as PauseEntry | null)?.reason);
    return reasons.some((reason) => !(SELF_RESUMING_PAUSES as readonly unknown[]).includes(reason));
}

function show(value: unknown): string {
    return typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value);
}

/** The decision the run waits for, e.g. `chain_exhausted step=build`. */
export function pauseText(pause: RunView['pause']): string | null {
    if (!pause) return null;
    const skip = new Set(['at', 'reason', 'waiting']);
    const detail = Object.entries(pause)
        .filter(([key, value]) => {
            if (skip.has(key) || value === null || value === undefined || value === '') return false;
            if (Array.isArray(value)) return value.length > 0;
            if (typeof value === 'object') return Object.keys(value).length > 0;
            return true;
        })
        .map(([key, value]) => `${key}=${show(value)}`)
        .join(' ');
    let text = `${pause.reason ?? 'paused'}${detail ? ` ${detail}` : ''}`;
    const waiting = Object.entries(pause.waiting ?? {});
    if (waiting.length > 1) {
        text += ` | waiting: ${waiting.map(([key, entry]) => `${key} (${entry?.reason ?? '?'})`).join(', ')}`;
    }
    return text;
}

function lastOf<T>(items: T[] | undefined): T | undefined {
    return items?.length ? items[items.length - 1] : undefined;
}

function bare(model: string): string {
    const name = model.trim().toLowerCase();
    return name.slice(name.lastIndexOf('/') + 1).replace(/-(?:\d{4}-\d{2}-\d{2}|\d{8})$/, '');
}

/** `requested→served` once an attempt has run (just the model when they match), else the model it will start on. */
export function modelText(step: StepView): string {
    const attempt = lastOf(step.attempt_history);
    let requested = attempt?.requested_model || attempt?.effective_model;
    const served = attempt?.served_model;
    if (!requested && !served) return String(step.chosen_model || step.chain?.[0] || '-');
    requested = requested || '-';
    if (served && requested !== '-' && bare(served) !== bare(requested)) return `${requested}→${served}`;
    return String(served || requested);
}

/** Fallback and last-attempt outcome, e.g. `fallback(usage_limit) acceptance_failed`. */
export function outcomeText(step: StepView): string | null {
    const parts: string[] = [];
    const attempt = lastOf(step.attempt_history);
    if (attempt?.fallback_used) parts.push(`fallback(${attempt.fallback_reason || '?'})`);
    const outcome = step.outcome ?? {};
    const reason = outcome.reason || attempt?.decision?.reason;
    if (reason && step.status !== 'pending') parts.push(String(reason));
    if (outcome.error && ['failed', 'refused', 'needs_owner'].includes(step.status)) {
        parts.push(`error=${JSON.stringify(String(outcome.error).slice(0, 80))}`);
    }
    return parts.join(' ') || null;
}

export interface StepSnapshot {
    status: string | undefined;
    attempts: number | undefined;
    model: string;
    outcome: string | null;
    ready: string | undefined;
    cancelling: boolean;
}

export interface RunSnapshot {
    state: string | undefined;
    pause: string | null;
    planRevision: number;
    cancelling: boolean;
    steps: Map<string, StepSnapshot>;
}

/**
 * What counts as a change: run state and pause, the plan, and each step's status, attempts, model and outcome.
 * Live phase and last-activity time move constantly and are left out.
 */
export function snapshotRun(run: RunView): RunSnapshot {
    const steps = new Map<string, StepSnapshot>();
    for (const step of run.steps ?? []) {
        steps.set(step.key, {
            status: step.status,
            attempts: step.attempts,
            model: modelText(step),
            outcome: outcomeText(step),
            ready: step.readiness?.state,
            cancelling: Boolean(step.cancelling),
        });
    }
    return {
        state: run.state,
        pause: pauseText(run.pause),
        planRevision: run.plan_revision ?? 0,
        cancelling: Boolean(run.cancelling),
        steps,
    };
}

export function snapshotsEqual(a: RunSnapshot, b: RunSnapshot): boolean {
    if (a.state !== b.state || a.pause !== b.pause || a.planRevision !== b.planRevision) return false;
    if (a.cancelling !== b.cancelling || a.steps.size !== b.steps.size) return false;
    for (const [key, step] of b.steps) {
        const before = a.steps.get(key);
        if (!before) return false;
        if (
            before.status !== step.status ||
            before.attempts !== step.attempts ||
            before.model !== step.model ||
            before.outcome !== step.outcome ||
            before.ready !== step.ready ||
            before.cancelling !== step.cancelling
        ) {
            return false;
        }
    }
    return true;
}

/** Plain lines describing what moved between two snapshots. */
export function diffSnapshots(old: RunSnapshot, next: RunSnapshot): string[] {
    const lines: string[] = [];
    if (old.state !== next.state) {
        lines.push(`run: ${old.state} → ${next.state}${next.pause ? ` (${next.pause})` : ''}`);
    } else if (old.pause !== next.pause) {
        lines.push(`run: pause ${old.pause || '-'} → ${next.pause || '-'}`);
    }
    if (old.planRevision !== next.planRevision) {
        lines.push(`plan: revision ${old.planRevision} → ${next.planRevision}`);
    }
    if (!old.cancelling && next.cancelling) lines.push('run: cancelling');
    for (const [key, step] of next.steps) {
        const before = old.steps.get(key);
        if (!before) {
            lines.push(`step ${key}: added (${step.status})`);
            continue;
        }
        const notes: string[] = [];
        if (before.status !== step.status) notes.push(`${before.status} → ${step.status}`);
        if (before.attempts !== step.attempts) notes.push(`attempt ${step.attempts}`);
        if (before.model !== step.model) notes.push(`model ${step.model}`);
        if (before.outcome !== step.outcome && step.outcome) notes.push(step.outcome);
        if (before.ready !== step.ready && step.status === 'pending') notes.push(step.ready || 'not pending');
        if (!before.cancelling && step.cancelling) notes.push('cancelling');
        if (notes.length) lines.push(`step ${key}: ${notes.join(', ')}`);
    }
    for (const key of old.steps.keys()) if (!next.steps.has(key)) lines.push(`step ${key}: removed`);
    return lines;
}

export type EndDecision =
    | { over: false }
    | { over: true; outcome: WaitOutcome; reason: string }
    | { over: true; error: 'step_not_in_run'; reason: string };

function runEnd(run: RunView): WaitOutcome | null {
    if (isFinishedRun(run.state)) return run.state as 'completed' | 'failed' | 'cancelled';
    if (needsDecision(run)) return 'needs_owner';
    return null;
}

/** Whether the wait is over for this view, and how. `baseline` is the first snapshot (needed for `any-change`). */
export function endOfWait(
    until: ReturnType<typeof parseUntil>,
    run: RunView,
    baseline: RunSnapshot | null,
): EndDecision {
    if (until.kind === 'step') {
        const step = run.steps?.find((s) => s.key === until.key);
        if (step && isFinishedStep(step.status)) {
            const ok = step.status === 'completed' || step.status === 'skipped';
            return {
                over: true,
                outcome: ok ? 'step_done' : 'step_ended',
                reason: `step ${until.key} ${step.status}`,
            };
        }
        if (!step && isFinishedRun(run.state)) {
            return { over: true, error: 'step_not_in_run', reason: `step ${until.key} is not in this run` };
        }
    } else if (until.kind === 'any-change' && baseline && !snapshotsEqual(snapshotRun(run), baseline)) {
        return { over: true, outcome: 'changed', reason: 'changed' };
    }
    const outcome = runEnd(run);
    return outcome ? { over: true, outcome, reason: `run ${run.state}` } : { over: false };
}
