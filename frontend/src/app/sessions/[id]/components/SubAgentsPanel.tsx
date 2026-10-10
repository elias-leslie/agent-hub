'use client'

import { useInfiniteQuery } from '@tanstack/react-query'
import { AlertCircle, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { querySessions } from '@/lib/api/sessions'
import {
  formatRelativeTime,
  formatTokens,
  getSessionLastActive,
  getSessionTitle,
  getUsageSummary,
} from '../../utils'
import { SessionStatusBadge } from './SessionHeader'
import { shortSessionId } from './session-display'
import { formatDate } from './utils'

export const SUB_AGENT_PAGE_SIZE = 50

export function SubAgentsPanel({
  parentId,
  expectedCount,
}: {
  parentId: string
  expectedCount: number
}) {
  const query = useInfiniteQuery({
    queryKey: ['session-children', parentId],
    queryFn: ({ pageParam }) =>
      querySessions({
        parent_session_id: parentId,
        page_size: SUB_AGENT_PAGE_SIZE,
        sort_by: 'last_active',
        cursor: pageParam || undefined,
      }),
    initialPageParam: '',
    getNextPageParam: (last) => last.next_cursor || undefined,
  })

  const pages = query.data?.pages ?? []
  const children = pages.flatMap((page) => page.sessions)
  const total = pages[0]?.total ?? expectedCount

  if (query.isLoading) {
    return (
      <p
        className="flex items-center gap-2 p-5 text-sm text-slate-400"
        role="status"
      >
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Loading sub-agents...
      </p>
    )
  }

  if (query.error && !query.data) {
    return (
      <div className="flex flex-wrap items-center gap-3 p-5 text-sm text-rose-700 dark:text-rose-300">
        <AlertCircle className="h-4 w-4" aria-hidden />
        <p role="status">Sub-agents are unavailable.</p>
        <button
          type="button"
          className="button-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          onClick={() => void query.refetch()}
        >
          Retry
        </button>
      </div>
    )
  }

  if (children.length === 0) {
    return (
      <p className="p-5 text-sm text-slate-400">
        No sub-agent sessions were returned for this session.
      </p>
    )
  }

  return (
    <div className="space-y-3 p-4 lg:p-5">
      <p className="text-xs text-slate-500" role="status">
        Showing {children.length.toLocaleString()} of {total.toLocaleString()}{' '}
        sub-agents, most recently active first
      </p>
      <ul className="divide-y divide-slate-800/70 rounded-xl border border-slate-800/80">
        {children.map((child) => {
          const usage = getUsageSummary(child)
          const lastActive = getSessionLastActive(child)
          const title = getSessionTitle(child)
          return (
            <li key={child.id}>
              <Link
                href={`/sessions/${child.id}`}
                className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1 px-3 py-2 text-sm hover:bg-slate-900/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-400 md:grid-cols-[auto_minmax(0,1fr)_auto_auto]"
              >
                <SessionStatusBadge status={child.status} />
                <span className="min-w-0">
                  <span className="block truncate text-slate-200" title={title}>
                    {title}
                  </span>
                  <span className="block truncate font-mono text-[11px] text-slate-500">
                    {shortSessionId(child.id)}
                    {child.agent_slug ? ` · ${child.agent_slug}` : ''}
                  </span>
                </span>
                <span
                  className="col-start-2 font-mono text-xs text-slate-400 md:col-start-auto"
                  title={usage.title}
                >
                  {usage.known
                    ? `${formatTokens(usage.input)} in / ${formatTokens(usage.output)} out`
                    : 'usage not captured'}
                </span>
                <time
                  dateTime={lastActive}
                  title={formatDate(lastActive)}
                  className="col-start-2 text-xs text-slate-500 md:col-start-auto"
                >
                  {formatRelativeTime(lastActive)}
                </time>
              </Link>
            </li>
          )
        })}
      </ul>
      {query.hasNextPage && (
        <div className="flex justify-center">
          <button
            type="button"
            className="button-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-60"
            disabled={query.isFetchingNextPage}
            onClick={() => void query.fetchNextPage()}
          >
            {query.isFetchingNextPage && (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            )}
            {query.isFetchingNextPage
              ? 'Loading more sub-agents...'
              : query.isFetchNextPageError
                ? 'Loading failed. Retry'
                : 'Load more sub-agents'}
          </button>
        </div>
      )}
    </div>
  )
}
