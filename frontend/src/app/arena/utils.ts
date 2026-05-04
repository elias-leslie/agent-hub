import type { AgentBenchmarkDashboard } from '@/app/agents/[slug]/analytics/types'
import type { ArenaAgentBenchmarkSummary } from './types'

export function formatRelativeTime(iso: string | null | undefined) {
  if (!iso) {
    return 'No completed runs yet'
  }
  const value = new Date(iso).getTime()
  if (Number.isNaN(value)) {
    return 'Unknown'
  }
  const diffMs = Date.now() - value
  const diffHours = Math.max(Math.round(diffMs / (1000 * 60 * 60)), 0)
  if (diffHours < 1) {
    return 'Less than an hour ago'
  }
  if (diffHours < 24) {
    return `${diffHours}h ago`
  }
  const diffDays = Math.round(diffHours / 24)
  if (diffDays < 30) {
    return `${diffDays}d ago`
  }
  return new Date(iso).toLocaleDateString()
}

export function formatArenaLabel(value: string | null | undefined) {
  if (!value) {
    return 'Unknown'
  }
  return value.replace(/\bjenny\b/gi, 'persona')
}

export function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return 'Pending'
  }
  return `${value.toFixed(1)}%`
}

export function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return 'Pending'
  }
  return value.toFixed(1)
}

export function summarizeArenaIssue(
  value: string | null | undefined,
  maxLength: number = 140,
) {
  if (!value) {
    return 'No issue captured'
  }
  const compact = value.replace(/\s+/g, ' ').trim()
  if (compact.length <= maxLength) {
    return compact
  }
  return `${compact.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`
}

export interface ArenaStatus {
  label: string
  tone: string
  detail: string
}

const STATUS_TONES = {
  pending: 'bg-slate-800 text-slate-200 ring-1 ring-slate-700',
  regression: 'bg-rose-950/30 text-rose-300 ring-1 ring-rose-800',
  watch: 'bg-amber-950/30 text-amber-300 ring-1 ring-amber-800',
  stable: 'bg-emerald-950/30 text-emerald-300 ring-1 ring-emerald-800',
} as const

export function deriveArenaStatusFromBenchmark(
  overview: Pick<
    ArenaAgentBenchmarkSummary,
    'total_runs' | 'avg_score' | 'pass_rate' | 'open_regressions'
  >,
): ArenaStatus {
  const {
    total_runs: totalRuns,
    avg_score: avgScore,
    pass_rate: passRate,
    open_regressions: regressions,
  } = overview
  if (totalRuns <= 0) {
    return {
      label: 'Collecting evidence',
      tone: STATUS_TONES.pending,
      detail:
        'Arena needs benchmark history before it can judge stability or regression pressure.',
    }
  }
  if (regressions >= 3 || (passRate !== null && passRate < 60)) {
    return {
      label: 'Regression pressure',
      tone: STATUS_TONES.regression,
      detail:
        'Arena is catching active failures that still need reduction before trust increases.',
    }
  }
  if (regressions > 0 || (avgScore !== null && avgScore < 90)) {
    return {
      label: 'Under watch',
      tone: STATUS_TONES.watch,
      detail:
        'Core behavior is mostly intact, but there are still open weaknesses in the benchmark battery.',
    }
  }
  return {
    label: 'Stable',
    tone: STATUS_TONES.stable,
    detail:
      'Recent runs are holding their ground with low regression pressure and solid benchmark scores.',
  }
}

export function deriveArenaStatus(
  benchmarkDashboard: AgentBenchmarkDashboard,
): ArenaStatus {
  return deriveArenaStatusFromBenchmark(benchmarkDashboard.overview)
}
