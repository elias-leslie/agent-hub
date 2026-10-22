'use client'

import Link from 'next/link'
import {
  Fragment,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { cn } from '@/lib/utils'
import { EmptyState } from './components/EmptyState'
import { ErrorAlert } from './components/ErrorAlert'
import { InfiniteScrollFooter } from './components/InfiniteScrollFooter'
import { LoadingState } from './components/LoadingState'
import { SessionInline } from './components/SessionInline'
import { SessionListHeader, SessionRow } from './components/SessionRow'
import { SessionsToolbar } from './components/SessionsToolbar'
import { useSessionKeyboard } from './hooks/useSessionKeyboard'
import {
  isDefaultFilterState,
  useSessionListState,
} from './hooks/useSessionListState'
import { useSessionsData } from './hooks/useSessionsData'

const FOLLOW_DELAY_MS = 250

function SessionsView() {
  const { state, update, select, clearFilters } = useSessionListState()
  const data = useSessionsData(state)
  const listRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const sentinelRef = useRef<HTMLDivElement>(null)
  const [cursorId, setCursorId] = useState<string | null>(state.selected)

  const selected = state.selected
  const expanded = selected !== null
  const ids = useMemo(() => data.sessions.map((s) => s.id), [data.sessions])
  const selectedRow = useMemo(
    () => data.sessions.find((s) => s.id === selected) ?? null,
    [data.sessions, selected],
  )

  useEffect(() => {
    if (selected) setCursorId(selected)
  }, [selected])

  // The cursor stays on its session across refetches; it only falls back to the
  // first row when its session is no longer in the list.
  const activeId =
    cursorId && ids.includes(cursorId) ? cursorId : (ids[0] ?? null)

  // Bring the expanded session's row into view when the selection changes.
  useEffect(() => {
    if (!selected) return
    const node = listRef.current?.querySelector<HTMLElement>(
      `[data-session-id="${CSS.escape(selected)}"]`,
    )
    node?.scrollIntoView({ block: 'nearest' })
  }, [selected])

  const { fetchNextPage, hasNextPage, isFetchingNextPage } = data
  useEffect(() => {
    const node = sentinelRef.current
    if (!node || !hasNextPage || typeof IntersectionObserver === 'undefined')
      return
    const observer = new IntersectionObserver(
      (entries) => {
        if (
          entries.some((entry) => entry.isIntersecting) &&
          !isFetchingNextPage
        ) {
          void fetchNextPage({ cancelRefetch: false })
        }
      },
      { rootMargin: '600px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [fetchNextPage, hasNextPage, isFetchingNextPage])

  const collapse = useCallback(() => select(null), [select])
  // While a session is expanded, j/k moves the expansion with the cursor,
  // debounced so holding a key does not load every session on the way.
  const followTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(
    () => () => {
      if (followTimer.current) clearTimeout(followTimer.current)
    },
    [],
  )
  const activate = useCallback(
    (id: string) => {
      setCursorId(id)
      if (!expanded) return
      if (followTimer.current) clearTimeout(followTimer.current)
      followTimer.current = setTimeout(() => select(id), FOLLOW_DELAY_MS)
    },
    [expanded, select],
  )
  const filterModel = useCallback(
    (model: string) => update({ model }),
    [update],
  )
  const handleRowClick = useCallback(
    (id: string) => {
      setCursorId(id)
      select(id === selected ? null : id)
    },
    [select, selected],
  )

  useSessionKeyboard({
    ids,
    activeId,
    expanded,
    listRef,
    searchRef,
    onActivate: activate,
    onToggle: (id) => select(id === selected ? null : id),
    onCollapse: collapse,
  })

  const ready = data.hasData && !data.error
  const showEmpty = ready && !data.isLoading && data.sessions.length === 0
  const filtersAreDefault = isDefaultFilterState(state)

  return (
    <div className="page-shell bg-slate-950 text-slate-100">
      <div className="page-backdrop bg-slate-950/90" />
      <header className="page-header bg-slate-950/92">
        <div className="page-container px-4 py-3 lg:px-8">
          <SessionsToolbar
            state={state}
            facets={data.facets}
            total={data.total}
            isFetching={data.isFetching}
            searchRef={searchRef}
            onChange={update}
            onRefresh={() => void data.refetch()}
          />
        </div>
      </header>

      <main className="relative px-0 md:px-4 lg:px-8">
        <div className="page-container">
          <Link
            href="/admin#activity"
            className="inline-block text-sm text-amber-300 underline focus-ring-amber my-3"
          >
            Work and admin activity across projects
          </Link>
          <div className="min-w-0 py-3">
            {data.error ? (
              <ErrorAlert
                error={data.error}
                onRetry={() => void data.refetch()}
              />
            ) : null}
            {data.isLoading ? <LoadingState /> : null}
            {showEmpty ? (
              <EmptyState
                kind={filtersAreDefault ? 'no-data' : 'no-match'}
                onClearFilters={clearFilters}
              />
            ) : null}

            {/* A selection outside the loaded rows (a sub-agent, or filtered out) opens above the list. */}
            {selected && !selectedRow && !data.isLoading ? (
              <div className="mb-3 overflow-hidden md:rounded-lg md:border md:border-slate-800">
                <SessionInline
                  key={selected}
                  sessionId={selected}
                  listRow={null}
                  onClose={collapse}
                  onSelect={select}
                  onFilterModel={filterModel}
                />
              </div>
            ) : null}

            {data.sessions.length > 0 ? (
              <div
                className={cn(
                  'overflow-hidden border-y border-slate-800 bg-slate-950/70 md:rounded-lg md:border',
                  data.isPlaceholder && 'opacity-70',
                )}
              >
                <SessionListHeader />
                <div
                  ref={listRef}
                  aria-label="Sessions"
                  data-testid="session-list"
                >
                  {data.sessions.map((session) => (
                    <Fragment key={session.id}>
                      <SessionRow
                        session={session}
                        isCursor={session.id === activeId}
                        isSelected={session.id === selected}
                        onClick={handleRowClick}
                      />
                      {session.id === selected ? (
                        <SessionInline
                          key={session.id}
                          sessionId={session.id}
                          listRow={session}
                          onClose={collapse}
                          onSelect={select}
                          onFilterModel={filterModel}
                        />
                      ) : null}
                    </Fragment>
                  ))}
                </div>
                <InfiniteScrollFooter
                  sessions={data.sessions}
                  total={data.total}
                  hasNextPage={hasNextPage}
                  isFetchingNextPage={isFetchingNextPage}
                  onLoadMore={() =>
                    void fetchNextPage({ cancelRefetch: false })
                  }
                />
                <div ref={sentinelRef} aria-hidden="true" />
              </div>
            ) : null}
          </div>
        </div>
      </main>
    </div>
  )
}

export default function SessionsPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <SessionsView />
    </Suspense>
  )
}
