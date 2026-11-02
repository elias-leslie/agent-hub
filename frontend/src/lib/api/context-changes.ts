/**
 * Context change review: what agents changed in memories, prompts and placement rules, and the owner's
 * keep / rework / refuse. Agents write with no gate; this is the after-the-fact review.
 * A null reach or token figure means not known yet, never zero.
 */

import { fetchApi, getApiBaseUrl } from '../api-config'
import { ContextHttpError } from './context-http'

const BASE = `${getApiBaseUrl()}/api/context-observability/changes`

export type TargetKind = 'memory' | 'prompt' | 'placement'
export type ChangeKind =
  | 'create'
  | 'update'
  | 'delete'
  | 'archive'
  | 'scope'
  | 'placement'
export type DecisionKind = 'keep' | 'rework' | 'refuse'

export interface Writer {
  /** owner | agent | client | system; null on rows written before writer capture. */
  kind: string | null
  session: string | null
  delivery: string | null
  harness: string | null
  work_role: string | null
  project: string | null
  coordinator: boolean | null
  resolved: boolean
}

export interface Receiver {
  harness: string
  role: string | null
  starts: number
}

export interface Reach {
  since: string
  until: string
  days: number
  starts: number
  subagent_starts: number
  starts_per_day: number
  receivers: Receiver[]
}

export interface ReviewHint {
  label: string
  decision: string
  confidence: number | null
  reason: string | null
  reviewed_at: string | null
}

export interface LaterWrite {
  revision: string
  at: string
  writer_kind: string | null
  action: string
  by: string | null
}

/**
 * Nightshift's hand-off of a row to an agent ("Look into it"). queued and working are open: asking again starts
 * nothing. unknown: Nightshift did not answer when the page loaded, which says nothing about whether one runs.
 */
export interface LookInto {
  state:
    | 'queued'
    | 'working'
    | 'fixed'
    | 'nothing'
    | 'needs-you'
    | 'failed'
    | 'ended'
    | 'unknown'
    | (string & {})
  /** One owner-facing line from Nightshift, e.g. "Agent working: Look into: …". */
  text: string
  /** The agent's Aico window; empty until it has one. */
  link: string
  id?: string | null
  revision?: string | null
}

export const LOOKINTO_OPEN = ['queued', 'working']

/** What a memory, prompt or placement layer looked like; placements carry only the rule list. */
export type TargetState = Record<string, unknown>

export interface QueueRow {
  key: string
  target_kind: TargetKind
  target_id: string
  title: string
  change: ChangeKind
  actions: string[]
  first_at: string
  last_at: string
  base_revision: string | null
  /** Sent back with every decision; a newer one returns 409. */
  through_revision: string
  version: number | null
  scope_before: string | null
  scope_after: string
  before: TargetState | null
  after: TargetState | null
  /** Tokens added per start (negative: removed). */
  delta_tokens: number | null
  tokens_per_day: number | null
  reach: Reach | null
  also_undoes: LaterWrite[]
  writers: Writer[]
  sessions: string[]
  linked: string[]
  hint: ReviewHint | null
  /** null: no hand-off for the revision shown. */
  lookinto?: LookInto | null
}

export interface AutomaticChange {
  key: string
  target_kind: TargetKind
  target_id: string
  title: string
  action: string
  at: string
  revision: string
  by: string | null
  reason: string | null
}

export interface Queue {
  rows: QueueRow[]
  summary: {
    count: number
    by_kind: Record<string, number>
    global_count: number
    tokens_per_day: number
    unknown_reach: number
  }
  automatic: AutomaticChange[]
}

export interface ReviewRecord {
  id: string
  target_kind: TargetKind
  target_id: string
  decision: DecisionKind
  through_revision: string
  result_revision: string | null
  note: string | null
  by: string | null
  by_kind: string | null
  created_at: string
  /** Decided by a look-into agent (its note starts "look-into <id>:"). */
  by_lookinto?: boolean
  lookinto?: LookInto | null
}

export interface ReviewItem {
  target_kind: TargetKind
  target_id: string
  through_revision: string
  expected_version?: number | null
}

export type Narrow =
  | { to: 'project'; project_id: string }
  | { to: 'role'; role: string }
  | { to: 'session' }

export interface Edit {
  content?: string
  summary?: string
  name?: string
}

export interface DecisionResult {
  key: string
  decision: DecisionKind
  outcome: string
  also_undid: LaterWrite[]
}

export interface DecideResponse {
  results: DecisionResult[]
  linked_pending: string[]
}

/** A decision the server did not take. `conflict` (409): the target changed since it was loaded. */
export class ReviewError extends Error {
  readonly status: number
  readonly kind: 'conflict' | 'invalid' | 'other'
  /** The row that moved, when the server names it. */
  readonly key: string | null

  constructor(status: number, message: string, key: string | null = null) {
    super(message)
    this.name = 'ReviewError'
    this.status = status
    this.key = key
    this.kind =
      status === 409 ? 'conflict' : status === 422 ? 'invalid' : 'other'
  }
}

interface ErrorBody {
  detail?:
    | string
    | { message?: string; key?: string | null }
    | { msg?: string; loc?: unknown[] }[]
}

async function failure(response: Response): Promise<ReviewError> {
  let body: ErrorBody = {}
  try {
    body = await response.json()
  } catch {
    // not JSON: fall through to the status text
  }
  const detail = body.detail
  let message = `Request failed (${response.status})`
  let key: string | null = null
  if (typeof detail === 'string') message = detail
  else if (Array.isArray(detail)) {
    message = detail
      .map((d) => d.msg)
      .filter(Boolean)
      .join('; ')
  } else if (detail && typeof detail === 'object') {
    message = detail.message ?? message
    key = detail.key ?? null
  }
  return new ReviewError(response.status, message, key)
}

async function getJson<T>(path: string, what: string): Promise<T> {
  const response = await fetchApi(`${BASE}${path}`)
  if (!response.ok) throw new ContextHttpError(response.status, what)
  return response.json()
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetchApi(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw await failure(response)
  return response.json()
}

export const fetchChanges = () => getJson<Queue>('', 'Loading changes')

export const DECISION_LIMIT = 500

export const fetchDecisions = () =>
  getJson<ReviewRecord[]>(
    `/decisions?limit=${DECISION_LIMIT}`,
    'Loading past decisions',
  )

export const itemOf = (row: QueueRow): ReviewItem => ({
  target_kind: row.target_kind,
  target_id: row.target_id,
  through_revision: row.through_revision,
  expected_version: row.version,
})

export const keepChanges = (items: ReviewItem[], note?: string) =>
  postJson<DecideResponse>('/keep', { items, note })

export const refuseChanges = (items: ReviewItem[], note?: string) =>
  postJson<DecideResponse>('/refuse', { items, note })

export const reworkChange = (
  item: ReviewItem,
  change: { edit: Edit } | { narrow: Narrow },
) => postJson<DecideResponse>('/rework', { ...item, ...change })

export interface LookIntoStarted {
  /** false: one was already open for this row, so nothing new started. */
  started: boolean
  lookinto: LookInto
}

/** Hand one row to an agent through Nightshift. 409: the row moved; 502: no agent was started. */
export const lookIntoChange = (
  row: QueueRow,
  note: string,
  model: string | null,
) =>
  postJson<LookIntoStarted>('/look-into', {
    target_kind: row.target_kind,
    target_id: row.target_id,
    through_revision: row.through_revision,
    note: note.trim() || null,
    model: model || null,
  })

export interface LookIntoModel {
  model: string
  tool: string
  effort: string | null
}

export interface LookIntoModels {
  /** The launch table's pick for the review role; null when it names none. */
  standard: LookIntoModel | null
  options: LookIntoModel[]
}

interface LaunchRow {
  tool: string
  model: string | null
  effort: string | null
  allowed: boolean
  launchable: boolean
  use: boolean
  alternates: { model?: string; effort?: string | null }[]
}

/** Models a Changes look-in can run, from the launch table's review rows (the first usable row is the default). */
export async function fetchLookIntoModels(): Promise<LookIntoModels> {
  const response = await fetchApi(
    `${getApiBaseUrl()}/api/models/launch-defaults?role=review`,
  )
  if (!response.ok)
    throw new ContextHttpError(response.status, 'Loading models')
  const data: { rows: LaunchRow[] } = await response.json()
  const options: LookIntoModel[] = []
  for (const row of data.rows) {
    if (!row.model || !row.launchable || !row.allowed || !row.use) continue
    const models = [
      { model: row.model, effort: row.effort },
      ...row.alternates.map((a) => ({
        model: a.model,
        effort: a.effort ?? null,
      })),
    ]
    // Nightshift runs a model on the first row that names it, so later rows add nothing.
    for (const m of models)
      if (m.model && !options.some((o) => o.model === m.model))
        options.push({ model: m.model, tool: row.tool, effort: m.effort })
  }
  return { standard: options[0] ?? null, options }
}

/** Titles for memory decisions (decisions carry only the id). Missing ids are simply absent. */
export async function fetchMemoryTitles(
  uuids: string[],
): Promise<Record<string, string>> {
  const titles: Record<string, string> = {}
  for (let i = 0; i < uuids.length; i += 100) {
    const response = await fetchApi(`${getApiBaseUrl()}/api/memory/batch-get`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uuids: uuids.slice(i, i + 100) }),
    })
    if (!response.ok) throw new Error(`Memory titles: ${response.status}`)
    const data: {
      episodes: Record<string, { summary?: string | null; name: string }>
    } = await response.json()
    for (const [id, e] of Object.entries(data.episodes)) {
      titles[id] = e.summary || e.name
    }
  }
  return titles
}
