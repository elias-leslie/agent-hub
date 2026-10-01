'use client'

import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { use, useCallback } from 'react'
import { EventTimeline } from '@/components/timeline'
import { fetchAllSessionEvents, fetchSession } from '@/lib/api'
import {
  combineNativeEvidencePages,
  fetchNativeEvidenceSummary,
  nativeEvidenceNextCursor,
} from '@/lib/api/native-evidence'
import { summarizeSessionMemoryObservability } from '@/lib/session-memory-observability'
import { cn } from '@/lib/utils'
import { NativeCapture } from './components/NativeCapture'
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

  const memorySummary = eventsData
    ? summarizeSessionMemoryObservability(eventsData.events)
    : null
  const {
    data: nativeEvidencePages,
    error: nativeEvidenceError,
    isLoading: nativeEvidenceLoading,
    isFetching: nativeEvidenceFetching,
    refetch: refetchNativeEvidence,
    fetchNextPage: loadMoreNativeEvidence,
    hasNextPage: nativeEvidenceHasMore,
    isFetchingNextPage: nativeEvidenceLoadingMore,
  } = useInfiniteQuery({
    queryKey: ['native-evidence', id],
    queryFn: ({ pageParam }) => fetchNativeEvidenceSummary(id, pageParam),
    initialPageParam: '',
    getNextPageParam: nativeEvidenceNextCursor,
    enabled: session?.provider === 'codex',
  })
  const nativeEvidence = nativeEvidencePages
    ? combineNativeEvidencePages(nativeEvidencePages.pages)
    : undefined

  return (
    <div
      className={cn(
        'page-shell text-slate-100',
        activeTab === 'timeline' && 'flex h-dvh min-h-0 flex-col',
      )}
    >
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
          activeTab === 'timeline'
            ? 'flex min-h-0 flex-1 flex-col'
            : 'page-frame',
        )}
      >
        {/* Error State */}
        {(sessionError || eventsError) && (
          <div className="px-4 py-6 lg:px-8">
            <div
              className={cn(
                'flex items-center gap-2 p-4 rounded-lg',
                'bg-red-950/40 border border-red-800/50',
                'text-red-400',
              )}
            >
              <AlertCircle className="h-5 w-5" />
              <p className="text-sm" role="status">
                {sessionError ? 'Session details are unavailable. ' : ''}
                {eventsError
                  ? eventsData
                    ? 'History refresh failed. Showing previously loaded events.'
                    : 'Session history is unavailable.'
                  : ''}
              </p>
            </div>
          </div>
        )}

        {/* Loading State */}
        {(sessionLoading || (activeTab === 'timeline' && eventsLoading)) &&
          !session &&
          !eventsData && (
            <div className="flex items-center justify-center h-full min-h-[24rem]">
              <div className="flex flex-col items-center gap-3 text-slate-500">
                <div className="w-8 h-8 border-2 border-slate-700 border-t-slate-400 rounded-full animate-spin" />
                <p className="text-sm">Loading session...</p>
              </div>
            </div>
          )}

        {/* Content */}
        {(session || eventsData) && (
          <>
            {session?.provider === 'codex' && (
              <NativeCapture
                session={session}
                evidence={nativeEvidence}
                evidenceLoading={nativeEvidenceLoading}
                evidenceError={!!nativeEvidenceError}
                evidenceFetching={nativeEvidenceFetching}
                onRefreshEvidence={() => void refetchNativeEvidence()}
                evidenceHasMore={nativeEvidenceHasMore}
                evidenceLoadingMore={nativeEvidenceLoadingMore}
                onLoadMoreEvidence={() => void loadMoreNativeEvidence()}
              />
            )}
            {activeTab === 'timeline' && eventsData && (
              <EventTimeline
                events={eventsData.events}
                nativeCommands={nativeEvidence?.commands}
                className="min-h-0 flex-1"
              />
            )}
            {activeTab === 'timeline' && eventsLoading && !eventsData && (
              <p className="p-4 text-sm text-slate-400" role="status">
                Loading session history...
              </p>
            )}
            {activeTab === 'info' && session && (
              <section className="panel-surface animate-fade-up">
                <SessionInfo
                  session={session}
                  events={eventsData?.events || []}
                  eventsTotal={eventsData?.total ?? null}
                  memorySummary={memorySummary}
                />
              </section>
            )}
          </>
        )}
      </main>
    </div>
  )
}
