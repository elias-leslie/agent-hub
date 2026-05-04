'use client'

import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useCallback, useState } from 'react'
import {
  fetchMemoryAnalytics,
  type MemoryAnalyticsDashboard,
} from '@/lib/memory-api'
import type { AnalyticsLookback } from './analytics-components'
import { EmptyState } from './analytics-components'
import { AnalyticsContent } from './analytics-content'
import { ErrorState, LoadingState } from './analytics-states'

const QUERY_CONFIG = {
  refetchInterval: 60000,
  staleTime: 30000,
} as const

export function AnalyticsTab() {
  const router = useRouter()
  const [lookback, setLookback] = useState<AnalyticsLookback>('30d')
  const [topMemoriesSortBy, setTopMemoriesSortBy] = useState('utility_score')

  const analyticsDays = lookback === '1h' ? 1 : Number.parseInt(lookback, 10)

  const navigateToEpisodes = useCallback(
    (filter: Record<string, string>) => {
      const params = new URLSearchParams(filter)
      router.push(`/memory?${params.toString()}`, { scroll: false })
    },
    [router],
  )

  const navigateToEpisode = useCallback(
    (uuid: string) => {
      router.push(`/memory?episode=${uuid}`, { scroll: false })
    },
    [router],
  )

  const {
    data: analytics,
    isLoading,
    error,
  } = useQuery<MemoryAnalyticsDashboard>({
    queryKey: ['memoryAnalytics', lookback, topMemoriesSortBy],
    queryFn: () =>
      fetchMemoryAnalytics({
        days: analyticsDays,
        lookback,
        sortBy: topMemoriesSortBy,
      }),
    ...QUERY_CONFIG,
  })

  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message={error.message} />
  if (!analytics || analytics.state.total_episodes === 0) return <EmptyState />

  return (
    <AnalyticsContent
      analytics={analytics}
      lookback={lookback}
      onLookbackChange={setLookback}
      topMemoriesSortBy={topMemoriesSortBy}
      onTopMemoriesSortChange={setTopMemoriesSortBy}
      onTierClick={(tier) => navigateToEpisodes({ category: tier })}
      onMemoryClick={navigateToEpisode}
    />
  )
}
