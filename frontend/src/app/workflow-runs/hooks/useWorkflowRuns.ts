import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
} from '@tanstack/react-query'
import { useMemo } from 'react'
import {
  fetchWorkflowRun,
  fetchWorkflowRuns,
  type WorkflowRunListItem,
} from '@/lib/api/workflow-runs'

/** Background tabs do not poll: react-query pauses intervals while hidden. */
const LIST_REFRESH_MS = 10_000
const DETAIL_REFRESH_MS = 3_000
/** A usage-limit pause resumes by itself, so a paused page still checks now and then. */
const PAUSED_REFRESH_MS = 15_000
const PAGE_SIZE = 50

export function useWorkflowRuns() {
  const list = useInfiniteQuery({
    queryKey: ['workflow-runs', 'list'],
    queryFn: ({ pageParam, signal }) =>
      fetchWorkflowRuns({ limit: PAGE_SIZE, offset: pageParam }, signal),
    initialPageParam: 0,
    getNextPageParam: (last) => {
      const next = last.offset + last.runs.length
      return last.runs.length > 0 && next < last.total ? next : undefined
    },
    placeholderData: keepPreviousData,
    refetchInterval: LIST_REFRESH_MS,
    refetchIntervalInBackground: false,
  })

  // Refetching several offset pages can overlap when runs arrive; keep the first copy.
  const runs = useMemo(() => {
    const seen = new Set<string>()
    const rows: WorkflowRunListItem[] = []
    for (const page of list.data?.pages ?? []) {
      for (const run of page.runs) {
        if (seen.has(run.id)) continue
        seen.add(run.id)
        rows.push(run)
      }
    }
    return rows
  }, [list.data])

  return {
    runs,
    total: list.data?.pages[0]?.total ?? 0,
    hasData: Boolean(list.data),
    isLoading: list.isLoading,
    isFetching: list.isFetching,
    error: list.error,
    updatedAt: list.dataUpdatedAt,
    refetch: list.refetch,
    fetchNextPage: list.fetchNextPage,
    hasNextPage: Boolean(list.hasNextPage),
    isFetchingNextPage: list.isFetchingNextPage,
  }
}

/** Polls while the run is working; stops once it has completed or failed. */
export function useWorkflowRun(id: string) {
  const query = useQuery({
    queryKey: ['workflow-runs', 'detail', id],
    queryFn: ({ signal }) => fetchWorkflowRun(id, signal),
    refetchInterval: (q) => {
      const state = q.state.data?.state
      if (state === 'completed' || state === 'failed') return false
      return state === 'needs_owner' ? PAUSED_REFRESH_MS : DETAIL_REFRESH_MS
    },
    refetchIntervalInBackground: false,
  })
  return {
    run: query.data ?? null,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    updatedAt: query.dataUpdatedAt,
    refetch: query.refetch,
  }
}
