import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import {
  REFRESH_OPTIONS,
  REFRESH_STORAGE_KEY,
  type RefreshInterval,
  SORT_STORAGE_KEY,
  type SortDirection,
  type SortField,
} from '../types'

const SORT_FIELDS: ReadonlySet<SortField> = new Set([
  'agent',
  'project',
  'status',
  'time',
])
const SORT_DIRECTIONS: ReadonlySet<SortDirection> = new Set(['asc', 'desc'])

export function useSessionPreferences() {
  const queryClient = useQueryClient()
  const [refreshInterval, setRefreshInterval] = useState<RefreshInterval>(0)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [sortField, setSortField] = useState<SortField>('status')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')

  // Load preferences from localStorage
  useEffect(() => {
    const storedRefresh = localStorage.getItem(REFRESH_STORAGE_KEY)
    if (storedRefresh) {
      const parsed = parseInt(storedRefresh, 10)
      if (REFRESH_OPTIONS.some((opt) => opt.value === parsed)) {
        setRefreshInterval(parsed as RefreshInterval)
      }
    }

    const storedSort = localStorage.getItem(SORT_STORAGE_KEY)
    if (storedSort) {
      try {
        const { field, direction } = JSON.parse(storedSort)
        if (SORT_FIELDS.has(field) && SORT_DIRECTIONS.has(direction)) {
          setSortField(field)
          setSortDirection(direction)
        }
      } catch {
        // ignore
      }
    }
  }, [])

  const handleRefreshChange = useCallback((interval: RefreshInterval) => {
    setRefreshInterval(interval)
    localStorage.setItem(REFRESH_STORAGE_KEY, String(interval))
  }, [])

  const handleSort = useCallback(
    (field: SortField) => {
      const newDirection =
        sortField === field && sortDirection === 'desc' ? 'asc' : 'desc'
      setSortField(field)
      setSortDirection(newDirection)
      localStorage.setItem(
        SORT_STORAGE_KEY,
        JSON.stringify({ field, direction: newDirection }),
      )
    },
    [sortField, sortDirection],
  )

  // Auto-refresh effect
  useEffect(() => {
    if (refreshInterval === 0) return
    const intervalId = setInterval(() => {
      setIsRefreshing(true)
      queryClient.invalidateQueries({ queryKey: ['sessions'] }).finally(() => {
        setTimeout(() => setIsRefreshing(false), 500)
      })
    }, refreshInterval)
    return () => clearInterval(intervalId)
  }, [refreshInterval, queryClient])

  return {
    refreshInterval,
    isRefreshing,
    sortField,
    sortDirection,
    handleRefreshChange,
    handleSort,
  }
}
