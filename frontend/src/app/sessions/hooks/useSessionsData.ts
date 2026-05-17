import { useInfiniteQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { fetchSessions } from '@/lib/api'
import type { SortDirection, SortField } from '../types'

interface UseSessionsDataProps {
  statusFilter: string
  projectFilter: string
  pageSize: number
  sortField: SortField
  sortDirection: SortDirection
}

export function useSessionsData({
  statusFilter,
  projectFilter,
  pageSize,
  sortField,
  sortDirection,
}: UseSessionsDataProps) {
  const {
    data,
    isLoading,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: [
      'sessions',
      {
        status: statusFilter,
        project: projectFilter,
        pageSize,
        sortField,
        sortDirection,
      },
    ],
    queryFn: ({ pageParam = 1 }) =>
      fetchSessions({
        page: pageParam,
        page_size: pageSize,
        status: statusFilter || undefined,
        project_id: projectFilter || undefined,
        sort_by: sortField,
        sort_direction: sortDirection,
      }),
    getNextPageParam: (lastPage) => {
      const totalPages = Math.ceil(lastPage.total / lastPage.page_size)
      return lastPage.page < totalPages ? lastPage.page + 1 : undefined
    },
    initialPageParam: 1,
  })

  const allSessions = useMemo(
    () => data?.pages.flatMap((page) => page.sessions) ?? [],
    [data],
  )

  const total = data?.pages[0]?.total ?? 0
  const loadedCount = allSessions.length

  return {
    data,
    allSessions,
    loadedCount,
    total,
    isLoading,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  }
}
