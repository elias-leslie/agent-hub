import { useMemo, useState } from 'react'
import type { SessionListItem } from '@/lib/api'
import type { ModelCost } from '@/lib/models'
import type { SortDirection, SortField } from '../types'
import {
  estimateCost,
  getSessionDescription,
  getSessionDisplayStatus,
} from '../utils'

interface UseSessionFiltersProps {
  sessions: SessionListItem[]
  modelCosts: Map<string, ModelCost>
  sortField: SortField
  sortDirection: SortDirection
  hideBenchmarkTraffic: boolean
}

export function useSessionFilters({
  sessions,
  modelCosts,
  sortField,
  sortDirection,
  hideBenchmarkTraffic,
}: UseSessionFiltersProps) {
  const [modelFilter, setModelFilter] = useState<string>('')
  const [searchQuery, setSearchQuery] = useState('')
  const hiddenBenchmarkCount = useMemo(
    () =>
      sessions.filter((session) => session.attribution_kind === 'benchmark')
        .length,
    [sessions],
  )

  const filteredAndSorted = useMemo(() => {
    let filtered = sessions

    if (hideBenchmarkTraffic) {
      filtered = filtered.filter(
        (session) => session.attribution_kind !== 'benchmark',
      )
    }

    // Filter by model
    if (modelFilter) {
      filtered = filtered.filter((s) => s.model === modelFilter)
    }

    // Filter by search
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter(
        (s) =>
          s.id.toLowerCase().includes(query) ||
          s.project_id.toLowerCase().includes(query) ||
          s.model.toLowerCase().includes(query) ||
          getSessionDescription(s).toLowerCase().includes(query) ||
          s.agent_slug?.toLowerCase().includes(query) ||
          s.request_source?.toLowerCase().includes(query) ||
          s.attribution_label?.toLowerCase().includes(query) ||
          s.attribution_detail?.toLowerCase().includes(query),
      )
    }

    // Sort
    const sorted = [...filtered].sort((a, b) => {
      let cmp = 0
      switch (sortField) {
        case 'agent':
          cmp =
            (a.agent_slug || '').localeCompare(b.agent_slug || '') ||
            a.model.localeCompare(b.model)
          break
        case 'project':
          cmp = a.project_id.localeCompare(b.project_id)
          break
        case 'status':
          cmp =
            getSessionDisplayStatus(a).rank - getSessionDisplayStatus(b).rank
          break
        case 'time':
          cmp =
            new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime()
          break
      }
      if (cmp === 0) {
        cmp =
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      }
      return sortDirection === 'asc' ? cmp : -cmp
    })

    return sorted
  }, [
    sessions,
    modelCosts,
    modelFilter,
    searchQuery,
    sortField,
    sortDirection,
    hideBenchmarkTraffic,
  ])

  const pageStats = useMemo(() => {
    if (!filteredAndSorted.length) return null
    const totalTokens = filteredAndSorted.reduce(
      (sum, s) => sum + s.total_input_tokens + s.total_output_tokens,
      0,
    )
    const totalCost = filteredAndSorted.reduce(
      (sum, s) =>
        sum +
        estimateCost(
          s.model,
          s.total_input_tokens,
          s.total_output_tokens,
          modelCosts,
        ),
      0,
    )
    return { totalTokens, totalCost }
  }, [filteredAndSorted, modelCosts])

  return {
    modelFilter,
    setModelFilter,
    searchQuery,
    setSearchQuery,
    hiddenBenchmarkCount,
    filteredAndSorted,
    visibleCount: filteredAndSorted.length,
    pageStats,
  }
}
