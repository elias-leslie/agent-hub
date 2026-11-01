import { RefreshCw } from 'lucide-react'
import { ContextHttpError } from '@/lib/api/context-http'
import { ago } from '../format'

/** A request failed. With stale data on screen the banner says so; without any, it replaces the content. */
export function FailedNotice({
  what,
  error,
  hasData,
  updatedAt,
  onRetry,
}: {
  what: string
  error: unknown
  hasData: boolean
  updatedAt?: number
  onRetry: () => void
}) {
  const owner = error instanceof ContextHttpError && error.needsOwner
  const reason = error instanceof Error ? error.message : 'unknown error'
  const loaded = updatedAt
    ? `, loaded ${ago(new Date(updatedAt).toISOString())}`
    : ''
  const text = owner
    ? hasData
      ? `Couldn't refresh ${what}: owner access is needed. Showing the last data${loaded}.`
      : `Couldn't load ${what}: owner access is needed. Open Agent Hub as the owner and retry.`
    : hasData
      ? `Couldn't refresh ${what} (${reason}). Showing the last data${loaded}.`
      : `Couldn't load ${what}: ${reason}.`
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2.5 text-sm text-red-200"
    >
      <span>{text}</span>
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex items-center gap-1 rounded-md border border-red-400/40 px-2 py-0.5 text-xs hover:bg-red-500/20 focus-ring-amber"
      >
        <RefreshCw className="h-3 w-3" />
        Retry
      </button>
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-xl bg-slate-800/40 ${className ?? ''}`}
    />
  )
}

export function EmptyNote({ children }: { children: React.ReactNode }) {
  return <p className="py-8 text-center text-sm text-slate-500">{children}</p>
}
