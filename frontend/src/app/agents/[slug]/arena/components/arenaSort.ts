import type {
  AgentBenchmarkCaseSummary,
  AgentBenchmarkModelSummary,
  AgentBenchmarkRunSummary,
  AgentBenchmarkSuiteSummary,
  AgentRegressionClusterSummary,
} from '@/app/agents/[slug]/analytics/types'

export function toSortableTime(iso: string | null | undefined) {
  if (!iso) {
    return 0
  }
  const value = new Date(iso).getTime()
  return Number.isNaN(value) ? 0 : value
}

export function sortModels(models: AgentBenchmarkModelSummary[]) {
  return [...models].sort((a, b) => {
    const scoreDelta = (b.avg_score ?? -1) - (a.avg_score ?? -1)
    if (scoreDelta !== 0) return scoreDelta
    const passDelta = b.pass_rate - a.pass_rate
    if (passDelta !== 0) return passDelta
    const toolDelta =
      (a.avg_tool_calls ?? Number.POSITIVE_INFINITY) -
      (b.avg_tool_calls ?? Number.POSITIVE_INFINITY)
    if (toolDelta !== 0) return toolDelta
    const tokenDelta =
      (a.avg_total_tokens ?? Number.POSITIVE_INFINITY) -
      (b.avg_total_tokens ?? Number.POSITIVE_INFINITY)
    if (tokenDelta !== 0) return tokenDelta
    const turnDelta =
      (a.avg_turns ?? Number.POSITIVE_INFINITY) -
      (b.avg_turns ?? Number.POSITIVE_INFINITY)
    if (turnDelta !== 0) return turnDelta
    return b.attempts - a.attempts
  })
}

export function sortRuns(runs: AgentBenchmarkRunSummary[]) {
  return [...runs].sort((a, b) => {
    const aValue = new Date(a.completed_at ?? a.started_at).getTime()
    const bValue = new Date(b.completed_at ?? b.started_at).getTime()
    return bValue - aValue
  })
}

export function sortRegressions(regressions: AgentRegressionClusterSummary[]) {
  return [...regressions].sort((a, b) => {
    if (b.occurrence_count !== a.occurrence_count)
      return b.occurrence_count - a.occurrence_count
    return (b.latest_avg_score ?? 0) - (a.latest_avg_score ?? 0)
  })
}

export function sortSuites(suites: AgentBenchmarkSuiteSummary[]) {
  return [...suites].sort((a, b) => {
    if (b.open_regressions !== a.open_regressions)
      return b.open_regressions - a.open_regressions
    if ((a.avg_score ?? 999) !== (b.avg_score ?? 999))
      return (a.avg_score ?? 999) - (b.avg_score ?? 999)
    if (b.run_count !== a.run_count) return b.run_count - a.run_count
    return (
      toSortableTime(b.latest_completed_at) -
      toSortableTime(a.latest_completed_at)
    )
  })
}

export function sortCases(cases: AgentBenchmarkCaseSummary[]) {
  return [...cases].sort((a, b) => {
    if (b.open_regressions !== a.open_regressions)
      return b.open_regressions - a.open_regressions
    if (a.pass_rate !== b.pass_rate) return a.pass_rate - b.pass_rate
    if ((a.avg_score ?? 999) !== (b.avg_score ?? 999))
      return (a.avg_score ?? 999) - (b.avg_score ?? 999)
    if (b.attempts !== a.attempts) return b.attempts - a.attempts
    return (
      toSortableTime(b.latest_completed_at) -
      toSortableTime(a.latest_completed_at)
    )
  })
}
