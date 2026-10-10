'use client'

import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { use, useCallback } from 'react'
import { EventTimeline } from '@/components/timeline'
import {
  combineNativeEvidencePages,
  fetchNativeEvidenceSummary,
  nativeEvidenceNextCursor,
} from '@/lib/api/native-evidence'
import { fetchSession } from '@/lib/api/sessions'
import { summarizeSessionMemoryObservability } from '@/lib/session-memory-observability'
import { cn } from '@/lib/utils'
import { NativeCapture } from './components/NativeCapture'
import {
  type SessionDetailTab,
  SessionHeader,
  sessionPanelId,
  sessionTabId,
} from './components/SessionHeader'
import { SessionInfo } from './components/SessionInfo'
import { SubAgentsPanel } from './components/SubAgentsPanel'
import {
  useSessionEventsSummary,
  useSessionTimeline,
  useTypedEventScan,
} from './hooks/useSessionTimeline'

const MEMORY_TYPES = ['memory_inject', 'memory_cite'] as const
const USAGE_TYPES = ['usage', 'usage_counter'] as const

function ErrorBanner({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-2 rounded-lg p-4',
        'bg-red-500/10 dark:bg-red-950/40 border border-red-800/50',
        'text-red-700 dark:text-red-400',
      )}
    >
      <AlertCircle className="h-5 w-5 shrink-0" aria-hidden />
      <p className="min-w-0 flex-1 text-sm" role="status">
        {message}
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="button-secondary py-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          Retry
        </button>
      )}
    </div>
  )
}

export default function SessionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const sessionQuery = useQuery({
    queryKey: ['session', id, { includeEvents: false }],
    queryFn: () => fetchSession(id, { includeEvents: false }),
  })
  const session = sessionQuery.data
  const parentId = session?.parent_session_id ?? null
  const { data: parent } = useQuery({
    queryKey: ['session', parentId, { includeEvents: false }],
    queryFn: () => fetchSession(parentId as string, { includeEvents: false }),
    enabled: !!parentId,
  })

  const hasChildren = (session?.child_session_count ?? 0) > 0
  const tabs: SessionDetailTab[] = hasChildren
    ? ['timeline', 'subagents', 'info']
    : ['timeline', 'info']
  const requestedTab = searchParams.get('tab')
  const activeTab: SessionDetailTab =
    requestedTab === 'info'
      ? 'info'
      : requestedTab === 'subagents' && hasChildren
        ? 'subagents'
        : 'timeline'
  const setActiveTab = useCallback(
    (tab: SessionDetailTab) => {
      const nextParams = new URLSearchParams(searchParams.toString())
      if (tab === 'timeline') nextParams.delete('tab')
      else nextParams.set('tab', tab)
      const query = nextParams.toString()
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      })
    },
    [pathname, router, searchParams],
  )

  const summaryQuery = useSessionEventsSummary(id)
  const summary = summaryQuery.data
  const timeline = useSessionTimeline(id, summary)

  // Memory refs need every memory event, not just the loaded window.
  const memoryScan = useTypedEventScan(id, MEMORY_TYPES, summary, true)
  // Without the summary or the scan, fall back to loaded events and say so.
  const memoryFallback = !summary || (!!memoryScan.error && !memoryScan.data)
  const memorySource = memoryFallback
    ? timeline.events
    : (memoryScan.data?.events ?? [])
  const memorySummary = summarizeSessionMemoryObservability(memorySource)
  const memoryPartial = memoryFallback
    ? timeline.server.hasMore || timeline.server.selectedTypes.size > 0
    : !!memoryScan.data && !memoryScan.data.complete

  // Usage records for the Info tab (excluded from the default timeline).
  const usageScan = useTypedEventScan(
    id,
    USAGE_TYPES,
    summary,
    activeTab === 'info',
  )
  const usageExpected = summary
    ? USAGE_TYPES.reduce((sum, type) => sum + (summary.by_type[type] ?? 0), 0)
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

  const fullHeight = activeTab === 'timeline'
  const initialLoading =
    sessionQuery.isLoading && !session && timeline.isLoading

  return (
    <div
      className={cn(
        'page-shell text-slate-100',
        fullHeight && 'flex h-dvh min-h-0 flex-col',
      )}
    >
      <div className="page-backdrop" />
      {session && (
        <SessionHeader
          session={session}
          sessionId={id}
          tabs={tabs}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          parent={parentId ? (parent ?? null) : undefined}
          eventsTotal={summary?.total ?? session.event_count ?? undefined}
          maxTurn={timeline.maxTurn}
          memorySummary={memorySummary}
          memoryPartial={memoryPartial}
        />
      )}

      <main
        className={cn(
          'page-container min-w-0',
          fullHeight ? 'flex min-h-0 flex-1 flex-col' : 'page-frame',
        )}
      >
        {(sessionQuery.error || timeline.error) && (
          <div className="space-y-2 px-4 py-4 lg:px-8">
            {sessionQuery.error && (
              <ErrorBanner
                message="Session details are unavailable."
                onRetry={() => void sessionQuery.refetch()}
              />
            )}
            {timeline.error && (
              <ErrorBanner
                message={
                  timeline.hasData
                    ? 'History refresh failed. Showing previously loaded events.'
                    : 'Session history is unavailable.'
                }
                onRetry={() => void timeline.refetch()}
              />
            )}
          </div>
        )}

        {initialLoading && (
          <div
            className="flex min-h-[24rem] items-center justify-center"
            role="status"
          >
            <div className="flex flex-col items-center gap-3 text-slate-500">
              <div
                className="h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-slate-400"
                aria-hidden
              />
              <p className="text-sm">Loading session...</p>
            </div>
          </div>
        )}

        {session?.provider === 'codex' && activeTab !== 'subagents' && (
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

        {activeTab === 'timeline' && (
          <section
            role="tabpanel"
            id={sessionPanelId('timeline')}
            aria-labelledby={session ? sessionTabId('timeline') : undefined}
            aria-label={session ? undefined : 'Timeline'}
            className="flex min-h-0 flex-1 flex-col"
          >
            {timeline.hasData ? (
              <EventTimeline
                events={timeline.events}
                nativeCommands={nativeEvidence?.commands}
                server={timeline.server}
                className="min-h-0 flex-1"
              />
            ) : (
              timeline.isLoading &&
              !initialLoading && (
                <p className="p-4 text-sm text-slate-400" role="status">
                  Loading session history...
                </p>
              )
            )}
          </section>
        )}

        {activeTab === 'subagents' && session && (
          <section
            role="tabpanel"
            id={sessionPanelId('subagents')}
            aria-labelledby={sessionTabId('subagents')}
            className="panel-surface animate-fade-up"
          >
            <SubAgentsPanel
              parentId={id}
              expectedCount={session.child_session_count ?? 0}
            />
          </section>
        )}

        {activeTab === 'info' && session && (
          <section
            role="tabpanel"
            id={sessionPanelId('info')}
            aria-labelledby={sessionTabId('info')}
            className="panel-surface animate-fade-up"
          >
            <SessionInfo
              session={session}
              events={usageScan.data?.events ?? []}
              eventsTotal={
                usageExpected === null || (usageExpected > 0 && !usageScan.data)
                  ? null
                  : usageExpected
              }
              eventsScopeLabel="usage events"
              eventsSummary={summary}
              memorySummary={memorySummary}
              memoryPartial={memoryPartial}
            />
          </section>
        )}
      </main>
    </div>
  )
}
