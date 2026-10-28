import { AlertCircle, RefreshCw } from 'lucide-react'

export function LoadingState({
  label = 'Loading workflow runs',
}: {
  label?: string
}) {
  return (
    <div aria-busy="true" aria-label={label} role="status">
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="flex h-10 items-center gap-3 border-b border-slate-800/50 px-3"
        >
          <div className="h-3 w-20 rounded bg-slate-800/80 animate-shimmer" />
          <div className="h-3 flex-1 rounded bg-slate-800/60 animate-shimmer" />
          <div className="hidden h-3 w-24 rounded bg-slate-800/60 animate-shimmer md:block" />
        </div>
      ))}
      <span className="sr-only">{label}</span>
    </div>
  )
}

export function ErrorAlert({
  title,
  error,
  onRetry,
  stale,
}: {
  title: string
  error: unknown
  onRetry: () => void
  /** Shown when older data is still on screen. */
  stale?: string | null
}) {
  const detail = error instanceof Error ? error.message : null
  return (
    <div
      role="alert"
      className="mb-4 flex flex-col gap-3 rounded-lg border border-rose-500/30 bg-rose-950/30 p-3 text-rose-100 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex items-start gap-2.5">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-300" />
        <div className="space-y-0.5">
          <p className="text-sm font-semibold">{title}</p>
          {stale ? <p className="text-xs text-rose-200/80">{stale}</p> : null}
          {detail ? (
            <p className="font-mono text-[11px] text-rose-200/70">{detail}</p>
          ) : null}
        </div>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex h-8 items-center gap-2 rounded-md border border-rose-400/30 bg-rose-500/10 px-3 text-xs font-medium text-rose-100 hover:bg-rose-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
      >
        <RefreshCw className="h-3.5 w-3.5" />
        Retry
      </button>
    </div>
  )
}
