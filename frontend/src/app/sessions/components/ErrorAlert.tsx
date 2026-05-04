import { AlertCircle, RefreshCw } from 'lucide-react'

export function ErrorAlert({
  error,
  onRetry,
}: {
  error?: unknown
  onRetry?: () => void
}) {
  const detail = error instanceof Error ? error.message : null

  return (
    <div className="mb-5 rounded-2xl border border-rose-500/30 bg-rose-950/30 p-4 text-rose-100 shadow-[0_0_0_1px_rgba(244,63,94,0.08)]">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-2 text-rose-300">
            <AlertCircle className="h-4 w-4" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-semibold">
              Unable to load sessions ledger
            </p>
            <p className="text-xs text-rose-200/80">
              The first page failed to load. Retry the request to recover the
              ledger.
            </p>
            {detail && (
              <p className="text-[11px] font-mono text-rose-200/70">{detail}</p>
            )}
          </div>
        </div>

        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center gap-2 rounded-xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-100 transition-colors hover:bg-rose-500/20"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Retry sessions
          </button>
        )}
      </div>
    </div>
  )
}
