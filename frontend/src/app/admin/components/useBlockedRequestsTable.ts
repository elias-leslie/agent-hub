import { useCallback, useEffect, useMemo, useState } from 'react'
import type { SortDirection } from '@/components/ui/SortableHeader'
import type { BlockedRequest } from '@/lib/api'
import type { SortField } from '../types'
import { downloadJson } from '../utils'
import type { RefreshInterval } from './tableConfig'

export function useBlockedRequestsTable(
  requests: BlockedRequest[],
  onRefresh: () => void,
) {
  const [searchQuery, setSearchQuery] = useState('')
  const [sortField, setSortField] = useState<SortField>('timestamp')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)
  const [focusedRowIndex, setFocusedRowIndex] = useState<number>(-1)
  const [clientFilter, setClientFilter] = useState<string | null>(null)
  const [refreshInterval, setRefreshInterval] = useState<RefreshInterval>(0)

  // Auto-refresh
  useEffect(() => {
    if (refreshInterval === 0) return
    const intervalId = setInterval(onRefresh, refreshInterval)
    return () => clearInterval(intervalId)
  }, [refreshInterval, onRefresh])

  // Get unique clients for filter
  const uniqueClients = useMemo(() => {
    const clients = new Set(
      requests.map((r) => r.client_name).filter(Boolean) as string[],
    )
    return Array.from(clients).sort()
  }, [requests])

  // Filter and search
  const filteredRequests = useMemo(() => {
    let filtered = requests

    // Client filter
    if (clientFilter) {
      filtered = filtered.filter((r) => r.client_name === clientFilter)
    }

    // Search
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      filtered = filtered.filter(
        (r) =>
          r.client_name?.toLowerCase().includes(q) ||
          r.endpoint.toLowerCase().includes(q) ||
          r.block_reason.toLowerCase().includes(q) ||
          r.source_path?.toLowerCase().includes(q),
      )
    }

    return filtered
  }, [requests, clientFilter, searchQuery])

  // Sort
  const sortedRequests = useMemo(() => {
    const items = [...filteredRequests]
    items.sort((a, b) => {
      let cmp = 0
      switch (sortField) {
        case 'timestamp':
          cmp =
            new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
          break
        case 'client_name':
          cmp = (a.client_name || '').localeCompare(b.client_name || '')
          break
        case 'endpoint':
          cmp = a.endpoint.localeCompare(b.endpoint)
          break
        case 'block_reason':
          cmp = a.block_reason.localeCompare(b.block_reason)
          break
      }
      return sortDirection === 'asc' ? cmp : -cmp
    })
    return items
  }, [filteredRequests, sortField, sortDirection])

  const handleSort = useCallback(
    (field: SortField) => {
      const newDirection =
        sortField === field && sortDirection === 'desc' ? 'asc' : 'desc'
      setSortField(field)
      setSortDirection(newDirection)
    },
    [sortField, sortDirection],
  )

  const handleToggleExpand = useCallback((index: number) => {
    setExpandedIndex((prev) => (prev === index ? null : index))
  }, [])

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!sortedRequests.length) return

      switch (e.key) {
        case 'ArrowDown':
        case 'j':
          e.preventDefault()
          setFocusedRowIndex((prev) =>
            Math.min(prev + 1, sortedRequests.length - 1),
          )
          break
        case 'ArrowUp':
        case 'k':
          e.preventDefault()
          setFocusedRowIndex((prev) => Math.max(prev - 1, 0))
          break
        case 'Enter':
        case ' ':
          e.preventDefault()
          if (focusedRowIndex >= 0 && focusedRowIndex < sortedRequests.length) {
            handleToggleExpand(focusedRowIndex)
          }
          break
        case 'Escape':
          e.preventDefault()
          setExpandedIndex(null)
          break
      }
    },
    [sortedRequests, focusedRowIndex, handleToggleExpand],
  )

  // Export to JSON
  const handleExport = useCallback(() => {
    const exportData = {
      exported_at: new Date().toISOString(),
      count: sortedRequests.length,
      requests: sortedRequests,
    }
    downloadJson(
      exportData,
      `blocked-requests-${new Date().toISOString().split('T')[0]}.json`,
    )
  }, [sortedRequests])

  return {
    searchQuery,
    setSearchQuery,
    sortField,
    sortDirection,
    expandedIndex,
    focusedRowIndex,
    clientFilter,
    setClientFilter,
    refreshInterval,
    setRefreshInterval,
    uniqueClients,
    sortedRequests,
    handleSort,
    handleToggleExpand,
    handleKeyDown,
    handleExport,
  }
}
