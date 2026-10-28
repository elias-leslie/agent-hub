'use client'

import { RefreshCw } from 'lucide-react'
import { ErrorAlert, LoadingState } from './components/ListStates'
import { RunRow, RunRowHeader } from './components/RunRow'
import { useWorkflowRuns } from './hooks/useWorkflowRuns'

function clock(ms: number): string {
  return ms ? new Date(ms).toLocaleTimeString() : ''
}

export default function WorkflowRunsPage() {
  const data = useWorkflowRuns()
  const failedWithData = data.error && data.hasData
  const empty = data.hasData && !data.error && data.runs.length === 0

  return (
    <div className="page-shell bg-slate-950 text-slate-100">
      <div className="page-backdrop bg-slate-950/90" />
      <header className="page-header bg-slate-950/92">
        <div className="page-container flex flex-wrap items-center gap-2 px-4 py-3 lg:px-8">
          <h1 className="mr-1 text-base font-semibold tracking-tight text-slate-100">
            Workflow runs
          </h1>
          {data.hasData ? (
            <span
              className="font-mono text-[12px] tabular-nums text-slate-400"
              data-testid="workflow-runs-total"
            >
              {data.total} {data.total === 1 ? 'run' : 'runs'}
            </span>
          ) : null}
          <div className="ml-auto flex items-center gap-2 text-[12px] text-slate-500">
            {data.updatedAt ? (
              <span>Updated {clock(data.updatedAt)}</span>
            ) : null}
            <button
              type="button"
              onClick={() => void data.refetch()}
              aria-label="Refresh workflow runs"
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-slate-800 bg-slate-950/60 px-2 text-slate-300 hover:border-slate-700 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
            >
              <RefreshCw
                className={
                  data.isFetching ? 'h-3.5 w-3.5 animate-spin' : 'h-3.5 w-3.5'
                }
              />
              Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="relative px-0 md:px-4 lg:px-8">
        <div className="page-container min-w-0 py-3">
          {data.error ? (
            <ErrorAlert
              title={
                failedWithData
                  ? 'Could not refresh workflow runs'
                  : 'Could not load workflow runs'
              }
              error={data.error}
              onRetry={() => void data.refetch()}
              stale={
                failedWithData
                  ? `Showing the list from ${clock(data.updatedAt)}; it may be out of date.`
                  : null
              }
            />
          ) : null}
          {data.isLoading ? <LoadingState /> : null}
          {empty ? (
            <p className="py-12 text-center text-sm text-slate-400">
              No workflow runs yet.
            </p>
          ) : null}
          {data.runs.length > 0 ? (
            <div className="overflow-hidden border-y border-slate-800 bg-slate-950/70 md:rounded-lg md:border">
              <RunRowHeader />
              <ul aria-label="Workflow runs" data-testid="workflow-run-list">
                {data.runs.map((run) => (
                  <RunRow key={run.id} run={run} />
                ))}
              </ul>
              {data.hasNextPage ? (
                <div className="border-t border-slate-800/60 p-2 text-center">
                  <button
                    type="button"
                    disabled={data.isFetchingNextPage}
                    onClick={() => void data.fetchNextPage()}
                    className="h-8 rounded-md border border-slate-800 bg-slate-950/60 px-3 text-[12px] text-slate-300 hover:border-slate-700 hover:text-slate-100 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
                  >
                    {data.isFetchingNextPage
                      ? 'Loading more'
                      : `Load more (${data.runs.length} of ${data.total})`}
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </main>
    </div>
  )
}
