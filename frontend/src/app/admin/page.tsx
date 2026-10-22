'use client'

import { AlertTriangle, RefreshCw, Shield, Zap } from 'lucide-react'
import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { fetchSessionHotspots, type SessionHotspots } from '@/lib/api'
import { fetchRequestBlockStats, type RequestBlockStats } from '@/lib/api/admin'
import { cn } from '@/lib/utils'
import { ActivityCostPanel } from './components/ActivityCostPanel'
import { SessionHotspotsPanel } from './components/SessionHotspotsPanel'

export default function AdminPage() {
  const [blockStats, setBlockStats] = useState<RequestBlockStats | null>(null)
  const [hotspots, setHotspots] = useState<SessionHotspots | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [activityError, setActivityError] = useState<string | null>(null)
  const [blockError, setBlockError] = useState(false)

  const refresh = useCallback(async () => {
    setIsRefreshing(true)
    try {
      const [blocks, activity] = await Promise.allSettled([
        fetchRequestBlockStats(),
        fetchSessionHotspots(),
      ])
      if (blocks.status === 'fulfilled') {
        setBlockStats(blocks.value)
        setBlockError(false)
      } else setBlockError(true)
      if (activity.status === 'fulfilled') {
        setHotspots(activity.value)
        setActivityError(null)
      } else
        setActivityError(
          activity.reason instanceof Error
            ? activity.reason.message
            : 'Request failed',
        )
    } finally {
      setIsRefreshing(false)
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 30000)
    return () => clearInterval(interval)
  }, [refresh])

  const todayBlocked = blockStats?.blocked_requests_today ?? null
  const unknownAttempts = blockStats?.unknown_client_requests_today ?? 0

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />

      {/* Header */}
      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 min-h-12 py-2 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <Shield className="h-5 w-5 shrink-0 text-slate-400" />
            <div className="min-w-0">
              <h1 className="text-base font-semibold text-slate-100">
                Work and admin activity
              </h1>
              <span className="text-xs text-slate-400">
                {isRefreshing ? 'Refreshing…' : 'Refreshes every 30s'}
              </span>
            </div>
          </div>

          <button
            onClick={refresh}
            disabled={isRefreshing}
            aria-label="Refresh activity data"
            className="p-1.5 rounded-md border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-400 transition-colors cursor-pointer"
            title="Refresh"
          >
            <RefreshCw
              className={cn('h-3.5 w-3.5', isRefreshing && 'animate-spin')}
            />
          </button>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-8 space-y-8 relative">
        <ActivityCostPanel
          activity={hotspots?.activity_cost ?? null}
          isLoading={isLoading}
          error={activityError}
          onRetry={refresh}
        />

        {blockError && (
          <p role="alert" className="text-sm text-amber-300">
            Request block stats could not be refreshed.
            {blockStats ? ' Showing the last loaded counts.' : ''}
          </p>
        )}
        {/* Stats Summary */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="p-5 rounded-xl bg-gradient-to-br from-amber-950/50 to-slate-900/40 border border-amber-800/50 hover:border-amber-700 transition-colors">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 rounded-lg bg-amber-900/30">
                <Zap className="w-4 h-4 text-amber-400" />
              </div>
              <span className="text-sm text-amber-400/80">Blocked Today</span>
            </div>
            <div className="text-3xl font-bold text-amber-400 tabular-nums">
              {todayBlocked ?? '—'}
            </div>
          </div>

          <div
            className={cn(
              'p-5 rounded-xl border transition-colors',
              unknownAttempts > 0
                ? 'bg-gradient-to-br from-red-950/50 to-slate-900/40 border-red-800/50 hover:border-red-700'
                : 'bg-gradient-to-br from-slate-900/80 to-slate-900/40 border-slate-800 hover:border-slate-700',
            )}
          >
            <div className="flex items-center gap-3 mb-3">
              <div
                className={cn(
                  'p-2 rounded-lg',
                  unknownAttempts > 0 ? 'bg-red-900/30' : 'bg-slate-800',
                )}
              >
                <AlertTriangle
                  className={cn(
                    'w-4 h-4',
                    unknownAttempts > 0 ? 'text-red-400' : 'text-slate-500',
                  )}
                />
              </div>
              <span
                className={cn(
                  'text-sm',
                  unknownAttempts > 0 ? 'text-red-400/80' : 'text-slate-400',
                )}
              >
                Unknown Clients
              </span>
            </div>
            <div
              className={cn(
                'text-3xl font-bold tabular-nums',
                unknownAttempts > 0 ? 'text-red-400' : 'text-slate-500',
              )}
            >
              {blockStats ? unknownAttempts : '—'}
            </div>
          </div>
        </div>

        {(hotspots || isLoading) && (
          <SessionHotspotsPanel hotspots={hotspots} isLoading={isLoading} />
        )}

        <section className="section-card flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="section-heading">Automations</h2>
            <p className="section-copy mt-1">
              Manage schedules and project policy in Automations.
            </p>
          </div>
          <Link href="/automations" className="button-secondary">
            Open Automations
          </Link>
        </section>
      </main>
    </div>
  )
}
