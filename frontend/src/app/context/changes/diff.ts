import type { QueueRow, TargetState } from '@/lib/api/context-changes'

export interface DiffLine {
  type: 'same' | 'add' | 'del'
  text: string
}

/** Longest-common-subsequence line diff; past the cap it shows everything removed, then everything added. */
const CELL_CAP = 4_000_000

export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before === '' ? [] : before.split('\n')
  const b = after === '' ? [] : after.split('\n')
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start++
  let endA = a.length
  let endB = b.length
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--
    endB--
  }
  const head = a
    .slice(0, start)
    .map((text): DiffLine => ({ type: 'same', text }))
  const tail = a.slice(endA).map((text): DiffLine => ({ type: 'same', text }))
  const x = a.slice(start, endA)
  const y = b.slice(start, endB)
  return [...head, ...middle(x, y), ...tail]
}

function middle(x: string[], y: string[]): DiffLine[] {
  if ((x.length + 1) * (y.length + 1) > CELL_CAP) {
    return [
      ...x.map((text): DiffLine => ({ type: 'del', text })),
      ...y.map((text): DiffLine => ({ type: 'add', text })),
    ]
  }
  const w = y.length + 1
  const table = new Uint32Array((x.length + 1) * w)
  for (let i = x.length - 1; i >= 0; i--) {
    for (let j = y.length - 1; j >= 0; j--) {
      table[i * w + j] =
        x[i] === y[j]
          ? table[(i + 1) * w + j + 1] + 1
          : Math.max(table[(i + 1) * w + j], table[i * w + j + 1])
    }
  }
  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) {
      out.push({ type: 'same', text: x[i] })
      i++
      j++
    } else if (table[(i + 1) * w + j] >= table[i * w + j + 1]) {
      out.push({ type: 'del', text: x[i++] })
    } else {
      out.push({ type: 'add', text: y[j++] })
    }
  }
  while (i < x.length) out.push({ type: 'del', text: x[i++] })
  while (j < y.length) out.push({ type: 'add', text: y[j++] })
  return out
}

export interface FieldChange {
  field: string
  label: string
  before: string
  after: string
}

const FIELD_LABELS: [string, string][] = [
  ['name', 'Name'],
  ['summary', 'Summary'],
  ['scope', 'Scope'],
  ['scope_id', 'Scope target'],
  ['tier', 'Tier'],
  ['status', 'Status'],
  ['context_kind', 'Kind'],
  ['roles', 'Roles'],
  ['trigger_task_types', 'Task types'],
  ['trigger_phases', 'Phases'],
  ['render_mode', 'Render mode'],
  ['prompt_type', 'Prompt type'],
  ['context_policy', 'Policy'],
]

function show(value: unknown): string {
  if (value === undefined || value === null || value === '') return 'none'
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'none'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** Non-text fields that differ. Content has its own line diff; token counts show in the row header. */
export function fieldChanges(
  before: TargetState | null,
  after: TargetState | null,
): FieldChange[] {
  if (!before || !after) return []
  return FIELD_LABELS.flatMap(([field, label]) => {
    if (
      JSON.stringify(before[field] ?? null) ===
      JSON.stringify(after[field] ?? null)
    )
      return []
    return [
      { field, label, before: show(before[field]), after: show(after[field]) },
    ]
  })
}

/** The text a state contributes to a diff: content for memories and prompts, the rule list for placements. */
export function bodyOf(state: TargetState | null): string {
  if (!state) return ''
  if (Array.isArray(state.placements)) {
    return state.placements.map((p) => JSON.stringify(p, null, 1)).join('\n')
  }
  return typeof state.content === 'string' ? state.content : ''
}

export interface RowDiff {
  fields: FieldChange[]
  lines: DiffLine[]
  added: number
  removed: number
}

export function rowDiff(row: Pick<QueueRow, 'before' | 'after'>): RowDiff {
  const lines = lineDiff(bodyOf(row.before), bodyOf(row.after))
  return {
    fields: fieldChanges(row.before, row.after),
    lines,
    added: lines.filter((l) => l.type === 'add').length,
    removed: lines.filter((l) => l.type === 'del').length,
  }
}
