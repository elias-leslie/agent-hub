import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useHydrated } from '@/hooks/use-hydrated'
import { useSessionEvents } from '@/hooks/use-session-events'
import { fetchDashboardStats, fetchSessions, fetchStatus } from '@/lib/api'

interface UseDashboardDataOptions {
  daysRange: number
}

export function useDashboardData({ daysRange }: UseDashboardDataOptions) {
  const { events } = useSessionEvents({ autoConnect: true })

  // Calculate active session count from recent events
  const activeSessionCount = useMemo(() => {
    const now = Date.now()
    const recentEvents = events.filter(
      (e) => now - new Date(e.timestamp).getTime() < 60000,
    )
    return new Set(recentEvents.map((e) => e.session_id)).size
  }, [events])

  // Status query. The app shell shares this key and hydrates first, so its
  // response can be cached before this page hydrates; hold it back until
  // hydration so the first render matches the server HTML.
  const hydrated = useHydrated()
  const statusQuery = useQuery({
    queryKey: ['status'],
    queryFn: fetchStatus,
    refetchInterval: 30000,
  })
  const status = hydrated ? statusQuery.data : undefined
  const statusLoading = hydrated ? statusQuery.isLoading : true
  const statusError = hydrated ? statusQuery.error : null

  // Sessions query
  const { data: sessionsData, isLoading: sessionsLoading } = useQuery({
    queryKey: ['sessions', 'recent'],
    queryFn: () => fetchSessions({ page_size: 10 }),
    refetchInterval: 30000,
  })

  // Dashboard stats query
  const { data: dashboardStats, isLoading: statsLoading } = useQuery({
    queryKey: ['dashboard-stats', daysRange],
    queryFn: () => fetchDashboardStats(daysRange),
    refetchInterval: 30000,
  })

  // Derived data. The request chart reads the same model-call population as
  // the KPIs (dashboard stats), not cost_logs row counts.
  const requestsByDay =
    dashboardStats?.requests_by_day.map((d) => d.requests) ?? []
  const requestTotal = dashboardStats?.requests.total_requests

  return {
    activeSessionCount,
    status,
    statusLoading,
    statusError,
    sessionsData,
    sessionsLoading,
    dashboardStats,
    statsLoading,
    requestsByDay,
    requestTotal,
  }
}
