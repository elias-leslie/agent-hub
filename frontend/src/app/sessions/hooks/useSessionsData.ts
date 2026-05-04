import { useInfiniteQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { fetchSessions } from '@/lib/api'

interface UseSessionsDataProps {
  statusFilter: string
  projectFilter: string
  pageSize: number
}

export function useSessionsData({
  statusFilter,
  projectFilter,
  pageSize,
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
      { status: statusFilter, project: projectFilter, pageSize },
    ],
    queryFn: ({ pageParam = 1 }) =>
      fetchSessions({
        page: pageParam,
        page_size: pageSize,
        status: statusFilter || undefined,
        project_id: projectFilter || undefined,
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
