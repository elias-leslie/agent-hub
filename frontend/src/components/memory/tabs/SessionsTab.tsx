'use client'

import { useQuery } from '@tanstack/react-query'
import { MonitorDot, RefreshCw } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import {
  SessionCard,
  type SessionMemoryInfo,
} from '@/components/memory/SessionCard'
import { getApiBaseUrl } from '@/lib/api-config'
import { apiFetch } from '@/lib/memory-utils'
import { cn } from '@/lib/utils'

const API_BASE = `${getApiBaseUrl()}/api`
const PAGE_SIZE = 30

interface SessionMemoryList {
  sessions: SessionMemoryInfo[]
  total: number
}

async function fetchSessionsWithMemory(
  limit: number,
  offset: number,
): Promise<SessionMemoryList> {
  const params = new URLSearchParams()
  params.set('limit', limit.toString())
  params.set('offset', offset.toString())
  return apiFetch<SessionMemoryList>(
    `${API_BASE}/memory/sessions-with-memory?${params}`,
    {},
    'Sessions fetch failed',
  )
}

function SessionSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="rounded-lg border border-slate-800 bg-slate-900/50 p-4 animate-pulse"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1 space-y-2">
              <div className="flex items-center gap-2">
                <div className="h-4 w-20 rounded bg-slate-800" />
                <div className="h-4 w-28 rounded bg-slate-800" />
                <div className="h-5 w-16 rounded-full bg-slate-800" />
              </div>
              <div className="flex items-center gap-4">
                <div className="h-3 w-32 rounded bg-slate-800" />
                <div className="h-3 w-12 rounded bg-slate-800" />
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="h-4 w-8 rounded bg-slate-800" />
              <div className="h-4 w-8 rounded bg-slate-800" />
              <div className="h-4 w-10 rounded bg-slate-800" />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

export function SessionsTab() {
  const [offset, setOffset] = useState(0)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['sessionsWithMemory', offset],
    queryFn: () => fetchSessionsWithMemory(PAGE_SIZE, offset),
    staleTime: 30000,
  })

  const handleRefresh = useCallback(() => {
    setIsRefreshing(true)
    refetch().finally(() => {
      setTimeout(() => setIsRefreshing(false), 400)
    })
  }, [refetch])

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1

  const goToPage = useCallback((page: number) => {
    setOffset((page - 1) * PAGE_SIZE)
    scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <div className="p-4 rounded-full bg-red-900/20 mb-4">
          <MonitorDot className="w-8 h-8 text-red-400" />
        </div>
        <h3 className="text-lg font-medium text-slate-100 mb-1">
          Failed to load sessions
        </h3>
        <p className="text-sm text-slate-400 max-w-sm mb-4">
          {(error as Error).message}
        </p>
        <button
          onClick={handleRefresh}
          className="px-4 py-2 rounded-lg bg-slate-800 text-sm text-slate-200 hover:bg-slate-700 transition-colors"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-slate-200">
            Sessions with Memory
          </h3>
          {data && (
            <span className="text-xs text-slate-500">{data.total} total</span>
          )}
        </div>
        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          className={cn(
            'p-2 rounded-lg transition-colors',
            'text-slate-400 hover:text-slate-200 hover:bg-slate-800',
            isRefreshing && 'cursor-not-allowed',
          )}
          title="Refresh"
        >
          <RefreshCw
            className={cn(
              'h-4 w-4',
              isRefreshing && 'animate-spin text-emerald-500',
            )}
          />
        </button>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-auto p-4">
        {isLoading ? (
          <SessionSkeleton />
        ) : data && data.sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="p-4 rounded-full bg-slate-800 mb-4">
              <MonitorDot className="w-8 h-8 text-slate-400" />
            </div>
            <h3 className="text-lg font-medium text-slate-100 mb-1">
              No sessions found
            </h3>
            <p className="text-sm text-slate-400 max-w-sm">
              Sessions with memory injection data will appear here
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {data?.sessions.map((session) => (
              <SessionCard key={session.session_id} session={session} />
            ))}
          </div>
        )}

        {data && data.total > PAGE_SIZE && (
          <div className="flex items-center justify-center gap-2 mt-6 pb-2">
            <button
              onClick={() => goToPage(currentPage - 1)}
              disabled={currentPage <= 1}
              className={cn(
                'px-3 py-1.5 rounded-md text-sm transition-colors',
                currentPage <= 1
                  ? 'text-slate-600 cursor-not-allowed'
                  : 'text-slate-300 bg-slate-800 hover:bg-slate-700',
              )}
            >
              Previous
            </button>
            <span className="text-xs text-slate-500 px-2">
              Page {currentPage} of {totalPages}
            </span>
            <button
              onClick={() => goToPage(currentPage + 1)}
              disabled={currentPage >= totalPages}
              className={cn(
                'px-3 py-1.5 rounded-md text-sm transition-colors',
                currentPage >= totalPages
                  ? 'text-slate-600 cursor-not-allowed'
                  : 'text-slate-300 bg-slate-800 hover:bg-slate-700',
              )}
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
