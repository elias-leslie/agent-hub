import {
  Activity,
  ArrowLeft,
  BookOpen,
  Clock,
  Hash,
  Layers,
  LayoutList,
} from 'lucide-react'
import Link from 'next/link'
import type { Session } from '@/lib/api'
import type { SessionMemoryObservability } from '@/lib/session-memory-observability'
import { cn } from '@/lib/utils'
import { formatDate, getProviderIcon } from './utils'

interface SessionHeaderProps {
  session: Session
  sessionId: string
  activeTab: 'timeline' | 'info'
  onTabChange: (tab: 'timeline' | 'info') => void
  eventsTotal?: number
  maxTurn?: number
  memorySummary?: SessionMemoryObservability | null
}

export function SessionHeader({
  session,
  sessionId,
  activeTab,
  onTabChange,
  eventsTotal,
  maxTurn,
  memorySummary,
}: SessionHeaderProps) {
  const requestedModel = session.requested_model || session.model
  const effectiveModel = session.effective_model || session.model
  const effectiveProvider = session.effective_provider || session.provider
  const showsFallback =
    session.fallback_used && requestedModel !== effectiveModel
  const liveActivity = session.live_activity
  const liveLabel = liveActivity
    ? `${liveActivity.health} · ${liveActivity.phase}`
    : null

  return (
    <header className="page-header">
      <div className="page-container px-4 lg:px-8">
        <div className="page-header-row">
          <div className="page-title-group">
            <Link
              href="/sessions"
              className="icon-button"
              aria-label="Back to sessions"
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>

            <div className="page-title-icon">
              {getProviderIcon(effectiveProvider)}
            </div>
            <div className="page-title-stack">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="page-title font-mono">
                  {sessionId.slice(0, 8)}
                </h1>
                <span
                  className={cn(
                    'page-pill',
                    session.status === 'active'
                      ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200'
                      : session.status === 'failed'
                        ? 'border-rose-500/20 bg-rose-500/10 text-rose-200'
                        : 'border-slate-700/80 bg-slate-900/90 text-slate-400',
                  )}
                >
                  {session.status}
                </span>
              </div>
              <div className="page-meta">
                <span className="page-pill">{effectiveProvider}</span>
                <span className="page-pill">{effectiveModel}</span>
                {showsFallback && (
                  <span className="page-pill border-amber-500/20 bg-amber-500/10 text-amber-100">
                    requested {requestedModel}
                  </span>
                )}
                {liveLabel && (
                  <span className="page-pill border-sky-500/20 bg-sky-500/10 text-sky-100">
                    {liveLabel}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="page-toolbar">
            <div className={cn('segmented-control')}>
              <button
                type="button"
                onClick={() => onTabChange('timeline')}
                className={cn(
                  'segmented-option',
                  activeTab === 'timeline'
                    ? 'border-amber-500/20 bg-amber-500/10 text-amber-100'
                    : 'hover:border-slate-700/80 hover:bg-slate-900/80 hover:text-slate-200',
                )}
              >
                <Activity className="h-3.5 w-3.5" />
                Timeline
              </button>
              <button
                type="button"
                onClick={() => onTabChange('info')}
                className={cn(
                  'segmented-option',
                  activeTab === 'info'
                    ? 'border-amber-500/20 bg-amber-500/10 text-amber-100'
                    : 'hover:border-slate-700/80 hover:bg-slate-900/80 hover:text-slate-200',
                )}
              >
                <LayoutList className="h-3.5 w-3.5" />
                Info
              </button>
            </div>

            {eventsTotal !== undefined && maxTurn !== undefined && (
              <div className="hidden md:flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <div className="page-pill">
                  <Hash className="h-3.5 w-3.5" />
                  <span className="font-mono">{eventsTotal} events</span>
                </div>
                <div className="page-pill">
                  <Layers className="h-3.5 w-3.5" />
                  <span className="font-mono">{maxTurn} turns</span>
                </div>
                {memorySummary && (
                  <div className="page-pill">
                    <BookOpen className="h-3.5 w-3.5" />
                    <span className="font-mono">
                      refs {memorySummary.selectedCount}/
                      {memorySummary.indexCount} cited{' '}
                      {memorySummary.selectedCitedCount}/
                      {memorySummary.selectedCount}
                    </span>
                  </div>
                )}
              </div>
            )}

            <div className="page-pill">
              <Clock className="h-3.5 w-3.5" />
              <span>{formatDate(session.created_at)}</span>
            </div>
          </div>
        </div>
      </div>
    </header>
  )
}
