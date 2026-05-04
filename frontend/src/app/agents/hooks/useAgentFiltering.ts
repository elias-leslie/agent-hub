import { useMemo } from 'react'
import type {
  Agent,
  AgentMetrics,
  SortDirection,
  SortField,
} from '../lib/types'

export function useAgentFiltering({
  agents,
  searchQuery,
  sortField,
  sortDirection,
  metricsData,
}: {
  agents: Agent[] | undefined
  searchQuery: string
  sortField: SortField
  sortDirection: SortDirection
  metricsData: Record<string, AgentMetrics> | undefined
}) {
  return useMemo(() => {
    if (!agents) return []

    // Hide persona agent — managed via /persona/settings
    let filtered = agents.filter((a) => a.slug !== 'persona')

    // Filter by search
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter(
        (a) =>
          a.slug.toLowerCase().includes(query) ||
          a.name.toLowerCase().includes(query) ||
          a.description?.toLowerCase().includes(query),
      )
    }

    // Sort
    return [...filtered].sort((a, b) => {
      let cmp = 0
      const metricsA = metricsData?.[a.slug]
      const metricsB = metricsData?.[b.slug]

      switch (sortField) {
        case 'name':
          cmp = a.name.localeCompare(b.name)
          break
        case 'model':
          cmp = a.primary_model_id.localeCompare(b.primary_model_id)
          break
        case 'requests':
          cmp = (metricsA?.requests_24h ?? 0) - (metricsB?.requests_24h ?? 0)
          break
        case 'latency':
          cmp =
            (metricsA?.avg_latency_ms ?? 0) - (metricsB?.avg_latency_ms ?? 0)
          break
        case 'cost':
          cmp = (metricsA?.cost_24h_usd ?? 0) - (metricsB?.cost_24h_usd ?? 0)
          break
      }
      return sortDirection === 'asc' ? cmp : -cmp
    })
  }, [agents, searchQuery, sortField, sortDirection, metricsData])
}
