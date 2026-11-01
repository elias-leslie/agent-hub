/**
 * Context observability: what each harness and role puts in front of the model on its first turn, and why it moved.
 * Every number can be null: null means not measured, never zero.
 */

import { fetchApi, getApiBaseUrl } from '../api-config'
import { ContextHttpError } from './context-http'

const BASE = `${getApiBaseUrl()}/api/context-observability`

export type ContextDays = 7 | 30 | 90
export const CONTEXT_DAYS: ContextDays[] = [7, 30, 90]

export interface MatrixCell {
  harness: string
  cell: string
  n: number
  total: number | null
  harness_tokens: number | null
  ours: number | null
  brief: number | null
  prev_n: number
  prev_total: number | null
  delta: number | null
  delta_pct: number | null
  latest_at: string
  version: string | null
  model: string | null
  warn_tokens: number | null
  jump_pct: number | null
  /**
   * warn: the last 24 h median is over the warn level. jump: the shown change (this range against the one before) is
   * jump_pct or more, with 5 starts in each. One rule for the flag, the sort and the header.
   */
  flag: 'warn' | 'jump' | null
  /** Why a change of jump_pct or more is not flagged (too few starts), else null. */
  flag_held: string | null
  recent: number | null
  n_recent: number
}

export interface HarnessInfo {
  harness: string
  version: string | null
  latest_at: string
  n: number
}

export interface Matrix {
  days: number
  generated_at: string
  /** First start of any kind. */
  coverage_from: string | null
  /** First start whose launched role was recorded; launched roles have no starts before it at any range. */
  launched_from: string | null
  jump_pct: number | null
  harnesses: HarnessInfo[]
  cells: MatrixCell[]
}

export interface TrendPoint {
  at: string
  total: number
  harness_tokens: number | null
  ours: number | null
  brief: number | null
  version: string | null
  model: string | null
}

export interface TrendDay {
  day: string
  n: number
  total: number | null
  harness_tokens: number | null
  ours: number | null
  brief: number | null
}

export interface VersionSighting {
  version: string
  first_at: string
  n: number
  initial: boolean
}

export interface StepMarker {
  at: string
  kind: string
  label: string
}

export type StepCause =
  | 'ours'
  | 'config'
  | 'harness_version'
  | 'harness'
  | 'model'
  | 'brief'
  | 'none'

export interface TrendStep {
  at: string
  kind: string
  cause: StepCause
  model: string | null
  delta: number
  pct: number
  before_total: number | null
  after_total: number | null
  n_before: number
  n_after: number
  parts: Record<string, number | null>
  summary: string
  markers: StepMarker[]
}

export interface TrendHeadline {
  n: number
  total: number | null
  harness_tokens: number | null
  ours: number | null
  brief: number | null
  prev_n: number
  prev_total: number | null
  delta: number | null
  delta_pct: number | null
}

export interface Trend {
  harness: string
  role: string
  days: number
  generated_at: string
  coverage_from: string | null
  latest_at: string | null
  jump_pct: number | null
  warn_tokens: number | null
  headline: TrendHeadline
  points: TrendPoint[]
  points_total: number
  daily: TrendDay[]
  versions: VersionSighting[]
  steps: TrendStep[]
  /** Days the chart shows moving by the step threshold that are not steps, with the reason. */
  dips: TrendDip[]
  /** Starts per model in the range; steps compare one model at a time, so a mix can explain a dip. */
  models: Array<{ model: string; n: number }>
}

export interface TrendDip {
  day: string
  total: number | null
  before_total: number | null
  pct: number
  n_day: number
  n_before: number
  reason: string
}

export interface PartValue {
  tokens: number | null
  method: string | null
}

export interface CellBlock {
  block_id: string
  source_type: string
  source_id: string
  label: string
  kind: string | null
  scope: string | null
  tokens: number
  revision: string | null
  writer_at: string | null
  writer_kind: string | null
  writer_session: string | null
  writer_action: string | null
}

export interface CellStart {
  at: string
  session_id: string
  total: number
  harness_tokens: number | null
  ours: number | null
  brief: number | null
  version: string | null
  model: string | null
  launch_mode: string
}

export interface CellGrowth {
  sessions: number
  measured: number
  median_peak: number | null
  max_peak: number | null
  median_first_turn: number | null
  compacted: number
  compactions: number
}

export interface CellState {
  harness: string
  cell: string
  n_recent: number
  recent: number | null
  n_baseline: number
  baseline: number | null
  warn_tokens: number | null
  jump_pct: number | null
  /** Last 24 h against the week before, same model, without the brief (body_recent against body_baseline). */
  body_pct: number | null
  body_recent: number | null
  body_baseline: number | null
  reason: 'warn' | 'jump' | null
}

export interface CellView {
  harness: string
  role: string
  generated_at: string
  lookback_days: number
  latest: CellStart | null
  config_fp: string | null
  delivery_id: string | null
  parts: Record<string, PartValue>
  blocks: CellBlock[]
  blocks_total: number | null
  budget_warn: number | null
  budget_jump_pct: number | null
  state: CellState | null
  growth: CellGrowth
  /** The median of every start in the lookback, to read next to the latest start. */
  median: {
    days: number
    n: number
    total: number | null
    harness_tokens: number | null
    ours: number | null
    brief: number | null
  } | null
  latest_move: {
    at: string
    kind: string
    cause: StepCause
    delta: number | null
    pct: number | null
    summary: string
  } | null
  recent: CellStart[]
}

async function getJson<T>(
  path: string,
  params: Record<string, string>,
): Promise<T> {
  const response = await fetchApi(
    `${BASE}/${path}?${new URLSearchParams(params)}`,
  )
  if (!response.ok) throw new ContextHttpError(response.status)
  return response.json()
}

export const fetchMatrix = (days: ContextDays) =>
  getJson<Matrix>('matrix', { days: String(days) })

export const fetchTrend = (harness: string, role: string, days: ContextDays) =>
  getJson<Trend>('trend', { harness, role, days: String(days) })

export const fetchCell = (harness: string, role: string) =>
  getJson<CellView>('cell', { harness, role })
