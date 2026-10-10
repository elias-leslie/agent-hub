'use client'

import { useRouter } from 'next/navigation'
import {
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { cn } from '@/lib/utils'
import { EmptyState } from './components/EmptyState'
import { ErrorAlert } from './components/ErrorAlert'
import { InfiniteScrollFooter } from './components/InfiniteScrollFooter'
import { LoadingState } from './components/LoadingState'
import { SessionPreview } from './components/SessionPreview'
import { SessionListHeader, SessionRow } from './components/SessionRow'
import { SessionsToolbar } from './components/SessionsToolbar'
import { useSessionKeyboard } from './hooks/useSessionKeyboard'
import {
  isDefaultFilterState,
  useSessionListState,
} from './hooks/useSessionListState'
import { useSessionsData } from './hooks/useSessionsData'

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const media = window.matchMedia(query)
    const sync = () => setMatches(media.matches)
    sync()
    media.addEventListener('change', sync)
    return () => media.removeEventListener('change', sync)
  }, [query])
  return matches
}

function SessionsView() {
  const router = useRouter()
  const { state, update, select, clearFilters } = useSessionListState()
  const data = useSessionsData(state)
  const rootRef = useRef<HTMLDivElement>(null)
  const headerRef = useRef<HTMLElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const sentinelRef = useRef<HTMLDivElement>(null)
  const [cursorId, setCursorId] = useState<string | null>(state.selected)
  const isSplit = useMediaQuery('(min-width: 1280px)')

  const selected = state.selected
  const previewOpen = selected !== null
  const compactRows = previewOpen && isSplit
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

  // Expose the sticky header height so the split preview can sit beneath it.
  useLayoutEffect(() => {
    const header = headerRef.current
    const root = rootRef.current
    if (!header || !root) return
    const sync = () =>
      root.style.setProperty('--sessions-top', `${header.offsetHeight}px`)
    sync()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(sync)
    observer.observe(header)
    return () => observer.disconnect()
  }, [])

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

  const openFull = useCallback(
    (id: string) => router.push(`/sessions/${id}`),
    [router],
  )
  const closePreview = useCallback(() => select(null), [select])
  const activate = useCallback(
    (id: string) => {
      setCursorId(id)
      if (previewOpen) select(id)
    },
    [previewOpen, select],
  )
  const handleRowClick = useCallback(
    (id: string) => {
      setCursorId(id)
      select(id)
    },
    [select],
  )
  const filterModel = useCallback(
    (model: string) => update({ model }),
    [update],
  )

  useSessionKeyboard({
    ids,
    activeId,
    previewOpen,
    listRef,
    searchRef,
    onActivate: activate,
    onOpenPreview: select,
    onClosePreview: closePreview,
    onOpenFull: openFull,
  })

  const ready = data.hasData && !data.error
  const showEmpty = ready && !data.isLoading && data.sessions.length === 0
  const filtersAreDefault = isDefaultFilterState(state)

  return (
    <div ref={rootRef} className="page-shell bg-slate-950 text-slate-100">
      <div className="page-backdrop bg-slate-950/90" />
      <header ref={headerRef} className="page-header bg-slate-950/92">
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
        <div
          className={cn(
            'page-container',
            previewOpen &&
              'xl:grid xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] xl:gap-4',
          )}
        >
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

            {data.sessions.length > 0 ? (
              <div
                className={cn(
                  'overflow-hidden border-y border-slate-800 bg-slate-950/70 md:rounded-lg md:border',
                  data.isPlaceholder && 'opacity-70',
                )}
              >
                <SessionListHeader compact={compactRows} />
                <div
                  ref={listRef}
                  role="listbox"
                  aria-label="Sessions"
                  data-testid="session-list"
                >
                  {data.sessions.map((session) => (
                    <SessionRow
                      key={session.id}
                      session={session}
                      isCursor={session.id === activeId}
                      isSelected={session.id === selected}
                      compact={compactRows}
                      onClick={handleRowClick}
                      onDoubleClick={openFull}
                    />
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

          {selected ? (
            <>
              <button
                type="button"
                aria-label="Close preview"
                tabIndex={-1}
                onClick={closePreview}
                className="fixed inset-0 z-30 hidden bg-black/50 md:block xl:hidden"
              />
              <SessionPreview
                key={selected}
                sessionId={selected}
                listRow={selectedRow}
                onClose={closePreview}
                onFilterModel={filterModel}
              />
            </>
          ) : null}
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
