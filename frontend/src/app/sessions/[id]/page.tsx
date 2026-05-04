'use client'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { use, useCallback } from 'react'
import { EventTimeline } from '@/components/timeline'
import { fetchAllSessionEvents, fetchSession } from '@/lib/api'
import { summarizeSessionMemoryObservability } from '@/lib/session-memory-observability'
import { cn } from '@/lib/utils'
import { SessionHeader } from './components/SessionHeader'
import { SessionInfo } from './components/SessionInfo'

export default function SessionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const activeTab = searchParams.get('tab') === 'info' ? 'info' : 'timeline'
  const setActiveTab = useCallback(
    (tab: 'timeline' | 'info') => {
      const nextParams = new URLSearchParams(searchParams.toString())
      if (tab === 'timeline') {
        nextParams.delete('tab')
      } else {
        nextParams.set('tab', tab)
      }
      const query = nextParams.toString()
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      })
    },
    [pathname, router, searchParams],
  )

  const {
    data: session,
    isLoading: sessionLoading,
    error: sessionError,
  } = useQuery({
    queryKey: ['session', id],
    queryFn: () => fetchSession(id),
  })

  const {
    data: eventsData,
    isLoading: eventsLoading,
    error: eventsError,
  } = useQuery({
    queryKey: ['session-events', id],
    queryFn: () => fetchAllSessionEvents(id, { page_size: 1000 }),
  })

  const isLoading = sessionLoading || eventsLoading
  const error = sessionError || eventsError
  const memorySummary = eventsData
    ? summarizeSessionMemoryObservability(eventsData.events)
    : null

  return (
    <div className="page-shell text-slate-100">
      <div className="page-backdrop" />
      {/* Header */}
      {session && (
        <SessionHeader
          session={session}
          sessionId={id}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          eventsTotal={eventsData?.total}
          maxTurn={eventsData?.max_turn}
          memorySummary={memorySummary}
        />
      )}

      {/* Main content */}
      <main
        className={cn(
          'page-container',
          activeTab === 'timeline' ? 'h-[calc(100vh-3.5rem)]' : 'page-frame',
        )}
      >
        {/* Error State */}
        {error && (
          <div className="px-4 py-6 lg:px-8">
            <div
              className={cn(
                'flex items-center gap-2 p-4 rounded-lg',
                'bg-red-950/40 border border-red-800/50',
                'text-red-400',
              )}
            >
              <AlertCircle className="h-5 w-5" />
              <p className="text-sm">Failed to load session</p>
            </div>
          </div>
        )}

        {/* Loading State */}
        {isLoading && (
          <div className="flex items-center justify-center h-full min-h-[24rem]">
            <div className="flex flex-col items-center gap-3 text-slate-500">
              <div className="w-8 h-8 border-2 border-slate-700 border-t-slate-400 rounded-full animate-spin" />
              <p className="text-sm">Loading session...</p>
            </div>
          </div>
        )}

        {/* Content */}
        {!isLoading && !error && session && (
          <>
            {activeTab === 'timeline' && eventsData && (
              <EventTimeline events={eventsData.events} className="h-full" />
            )}
            {activeTab === 'info' && (
              <section className="panel-surface animate-fade-up">
                <SessionInfo session={session} memorySummary={memorySummary} />
              </section>
            )}
          </>
        )}
      </main>
    </div>
  )
}
