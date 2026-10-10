import { RefreshCw } from 'lucide-react'
import type { SessionListItem } from '@/lib/api/sessions'
import { formatTokens, getUsageSummary } from '../utils'

const COUNT = new Intl.NumberFormat('en-US')

export function InfiniteScrollFooter({
  sessions,
  total,
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
}: {
  sessions: SessionListItem[]
  total: number
  hasNextPage: boolean
  isFetchingNextPage: boolean
  onLoadMore: () => void
}) {
  if (sessions.length === 0) return null

  let input = 0
  let output = 0
  let known = 0
  for (const session of sessions) {
    const usage = getUsageSummary(session)
    if (!usage.known) continue
    known += 1
    input += usage.input
    output += usage.output
  }

  return (
    <div
      data-testid="sessions-footer"
      className="flex flex-wrap items-center justify-between gap-2 px-3 py-3 text-[12px] text-slate-500"
    >
      <span data-testid="sessions-loaded-count">
        {hasNextPage
          ? `Partial: showing ${COUNT.format(sessions.length)} of ${COUNT.format(total)}`
          : `All ${COUNT.format(sessions.length)} shown`}
      </span>
      <span title="Totals cover only loaded sessions whose harness reported usage">
        Tokens in {formatTokens(input)} · out {formatTokens(output)} across{' '}
        {COUNT.format(known)} of {COUNT.format(sessions.length)} loaded with
        usage
      </span>
      {hasNextPage ? (
        <button
          type="button"
          onClick={onLoadMore}
          disabled={isFetchingNextPage}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-800 px-2.5 py-1 text-slate-300 hover:border-slate-700 hover:bg-slate-900 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
        >
          {isFetchingNextPage ? (
            <RefreshCw className="h-3 w-3 animate-spin" />
          ) : null}
          Load more
        </button>
      ) : null}
    </div>
  )
}
