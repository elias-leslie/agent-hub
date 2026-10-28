/**
 * Workflow runs, written by hand: the request bodies from `backend/app/services/workflow_runs/schemas.py`, the run view
 * from `get_run_view` in `engine.py` (the OpenAPI describes these routes' responses only as free-form objects, so
 * there is nothing to generate them from). Fields the backend adds later are kept by the `[key: string]: unknown`
 * index on the view types.
 */

export type RunState = 'running' | 'needs_owner' | 'completed' | 'failed' | 'cancelled' | (string & {});

export type StepStatus =
    | 'pending'
    | 'running'
    | 'needs_owner'
    | 'completed'
    | 'skipped'
    | 'cancelled'
    | 'failed'
    | 'refused'
    | (string & {});

export interface AcceptanceCommand {
    cmd: string;
    timeout_s?: number | null;
}

export interface StepDefinition {
    /** `^[a-z0-9][a-z0-9_-]{0,63}$` */
    key: string;
    instructions: string;
    /** The step's ordered model chain is this agent's route. */
    agent_slug: string;
    model_override?: string | null;
    allowed_models?: string[] | null;
    executor?: string | null;
    /** Tool level: read, lean or full. */
    level?: string | null;
    /** A bare string is a command without a time limit. */
    acceptance?: Array<AcceptanceCommand | string>;
    effort?: string | null;
    max_attempts?: number | null;
    workflow_ids?: string[];
    /** Steps that must complete first. Unset: depends on the step before it; `[]`: depends on nothing. */
    depends_on?: string[] | null;
}

export interface RunDefinition {
    goal: string;
    project_id: string;
    steps: StepDefinition[];
    repo_path?: string | null;
    base_ref?: string;
    task_id?: string | null;
    /** Makes creation idempotent: the same id returns the same run with `created: false`. */
    request_id?: string | null;
    policy?: Record<string, unknown>;
    launched_by?: string | null;
    coordinator?: string | null;
}

export interface PlanChange {
    changed_by?: string | null;
    reason?: string | null;
}

export interface AddStepsRequest extends PlanChange {
    steps: StepDefinition[];
    /** Shorthand: the first added step without its own `depends_on` depends on this step. */
    after?: string | null;
}

/** Only the fields sent change; a field sent as `null` is cleared (except instructions, agent_slug, acceptance). */
export interface StepRevision extends PlanChange {
    instructions?: string;
    agent_slug?: string;
    model_override?: string | null;
    allowed_models?: string[] | null;
    executor?: string | null;
    level?: string | null;
    effort?: string | null;
    acceptance?: Array<AcceptanceCommand | string>;
    max_attempts?: number | null;
    depends_on?: string[] | null;
}

export interface RunRevision extends PlanChange {
    /** Steps that may run at once. */
    max_concurrent_steps?: number;
}

export interface RemoveStepRequest extends PlanChange {
    /** Steps that depended on the removed one, revised in the same call (by step key). */
    revise?: Record<string, StepRevision>;
}

/** How the owner resolves a paused run. */
export interface OwnerDecision {
    action: 'retry' | 'skip' | 'fail';
    /** Which waiting step; needed when several wait. */
    step_key?: string | null;
    /** retry only: pin the step to this model. */
    model?: string | null;
    note?: string | null;
    /** retry only: attempts to allow past the step's cap. */
    extra_attempts?: number | null;
}

export interface CancelOptions {
    reason?: string | null;
}

export interface PauseEntry {
    reason?: string;
    [key: string]: unknown;
}

/** Why a run waits for the owner. `waiting` has one entry per step waiting. */
export interface Pause {
    reason?: string;
    /** When the run paused, in epoch seconds (the server stores its clock as a number, not text). */
    at?: number;
    waiting?: Record<string, PauseEntry | null>;
    [key: string]: unknown;
}

export interface StepAttempt {
    session_id?: string;
    attempt: number;
    status?: string;
    requested_model?: string | null;
    effective_model?: string | null;
    served_model?: string | null;
    fallback_used?: boolean | null;
    fallback_reason?: string | null;
    decision?: { reason?: string; [key: string]: unknown } | null;
    [key: string]: unknown;
}

export interface StepReadiness {
    state?: string;
    reason?: string;
    [key: string]: unknown;
}

export interface StepView {
    key: string;
    position?: number;
    status: StepStatus;
    agent_slug?: string;
    chain?: string[] | null;
    chosen_model?: string | null;
    depends_on?: string[];
    readiness?: StepReadiness | null;
    attempts?: number;
    attempt_limit?: number;
    outcome?: { reason?: string; error?: unknown; [key: string]: unknown } | null;
    cancelling?: boolean;
    attempt_history?: StepAttempt[];
    handoff?: unknown;
    [key: string]: unknown;
}

export interface RunView {
    id: string;
    state: RunState;
    goal?: string;
    project_id?: string;
    pause?: Pause | null;
    failure?: unknown;
    cancel?: { reason?: string | null; [key: string]: unknown } | null;
    cancelling?: boolean;
    plan_revision?: number;
    launched_by?: string | null;
    coordinator?: string | null;
    max_concurrent_steps?: number;
    running_steps?: string[];
    created_at?: string | null;
    last_activity_at?: string | null;
    steps: StepView[];
    [key: string]: unknown;
}

export interface CreatedRun extends RunView {
    /** False when `request_id` matched a run that already exists. */
    created: boolean;
}

export interface RunListItem {
    id: string;
    state: RunState;
    goal?: string | null;
    project_id?: string;
    launched_by?: string | null;
    coordinator?: string | null;
    plan_revision?: number;
    pause_reason?: string | null;
    failure?: unknown;
    created_at?: string | null;
    last_activity_at?: string | null;
    step_total?: number;
    step_counts?: Record<string, number>;
    [key: string]: unknown;
}

export interface RunList {
    runs: RunListItem[];
    total: number;
    limit: number;
    offset: number;
}

export interface ListRunsParams {
    /** 1 to 200; default 50. */
    limit?: number;
    offset?: number;
    /** Only runs launched by this session (the run's `launched_by`). */
    launched_by?: string;
    /** Only runs of this coordinator (the run's `coordinator`). */
    coordinator?: string;
}

/** Result of resume / cancel / cancel step: the run's new state. */
export interface RunAction {
    run_id?: string;
    state: RunState;
    cancelling?: boolean;
    [key: string]: unknown;
}

/** Result of a plan change (revise, add steps, revise or remove a step): what changed, and the run after it. */
export interface RevisionResult {
    run_id: string;
    state: RunState;
    plan_revision: number;
    run: RunView | null;
    [key: string]: unknown;
}
