import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useSessionEvents } from '@/hooks/use-session-events'
import {
  fetchCosts,
  fetchDashboardStats,
  fetchSessions,
  fetchStatus,
} from '@/lib/api'

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

  // Status query
  const {
    data: status,
    isLoading: statusLoading,
    error: statusError,
  } = useQuery({
    queryKey: ['status'],
    queryFn: fetchStatus,
    refetchInterval: 30000,
  })

  // Cost queries
  const { data: dailyCosts, isLoading: dailyLoading } = useQuery({
    queryKey: ['costs', 'day', daysRange],
    queryFn: () => fetchCosts({ group_by: 'day', days: daysRange }),
    refetchInterval: 60000,
  })

  const { data: totalCosts } = useQuery({
    queryKey: ['costs', 'none', daysRange],
    queryFn: () => fetchCosts({ group_by: 'none', days: daysRange }),
    refetchInterval: 60000,
  })

  const { data: costsByProject, isLoading: projectLoading } = useQuery({
    queryKey: ['costs', 'project', daysRange],
    queryFn: () => fetchCosts({ group_by: 'project', days: daysRange }),
    refetchInterval: 60000,
  })

  const { data: costsByModel, isLoading: modelLoading } = useQuery({
    queryKey: ['costs', 'model', daysRange],
    queryFn: () => fetchCosts({ group_by: 'model', days: daysRange }),
    refetchInterval: 60000,
  })

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

  // Derived data
  const requestsByDay =
    dailyCosts?.aggregations.map((a) => a.request_count) || []
  const costByDay = dailyCosts?.aggregations.map((a) => a.total_cost_usd) || []

  return {
    activeSessionCount,
    status,
    statusLoading,
    statusError,
    dailyCosts,
    dailyLoading,
    totalCosts,
    costsByProject,
    projectLoading,
    costsByModel,
    modelLoading,
    sessionsData,
    sessionsLoading,
    dashboardStats,
    statsLoading,
    requestsByDay,
    costByDay,
  }
}
