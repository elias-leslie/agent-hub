'use client'

import { formatDistanceToNowStrict } from 'date-fns'
import { Command, RefreshCw, Square } from 'lucide-react'

import type { Session, SessionListItem } from '@/lib/api/sessions'
import type { PersonaRuntimeState } from '../hooks/usePersonaRuntime'
import { prettifyDisplayText, shortenText } from './workspace-format'

interface PersonaRunHudProps {
  personaName: string
  runtime: PersonaRuntimeState
  session?: SessionListItem | null
  sessionDetails?: Session | null
  onStop?: () => void
  onRefresh: () => void
  onOpenCommands: () => void
  compact?: boolean
}

export function PersonaRunHud({
  runtime,
  session,
  sessionDetails,
  onStop,
  onRefresh,
  onOpenCommands,
  compact = false,
}: PersonaRunHudProps) {
  const primary = session ?? runtime.primarySession
  const details =
    sessionDetails ??
    (primary?.id === runtime.primarySessionDetails?.id
      ? runtime.primarySessionDetails
      : null)
  const liveActivity = primary?.live_activity ?? null
  const activeChildLaneCount = runtime.activeChildSessions.filter(
    (child) =>
      child.status === 'active' || child.live_activity?.status === 'active',
  ).length
  const elapsed = primary?.created_at
    ? formatDistanceToNowStrict(new Date(primary.created_at), {
        addSuffix: false,
      })
    : null
  const summary = liveActivity?.summary
    ? shortenText(
        prettifyDisplayText(liveActivity.summary) || liveActivity.summary,
        compact ? 120 : 180,
      )
    : ''
  const stopEnabled = Boolean(
    primary &&
      (primary.status === 'active' || liveActivity?.status === 'active'),
  )
  const meta = [
    elapsed ? `elapsed ${elapsed}` : null,
    details?.context_usage
      ? `context ${Math.round(details.context_usage.percent_used)}%`
      : null,
    activeChildLaneCount > 0 ? `${activeChildLaneCount} lanes` : null,
    liveActivity?.current_tool_name || liveActivity?.last_tool_name || null,
  ].filter(Boolean)
  const shellClassName = compact
    ? 'flex items-start justify-between gap-3'
    : 'rounded-lg border border-slate-800/70 bg-slate-950/70 p-4'

  return (
    <div data-testid="persona-run-hud" className={shellClassName}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {summary ? (
            <div className="text-sm font-medium text-slate-100">{summary}</div>
          ) : null}
          {meta.length > 0 ? (
            <div className="mt-2 text-xs text-slate-500">
              {meta.join(' · ')}
            </div>
          ) : null}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onRefresh}
            className="rounded-lg border border-slate-800 bg-slate-950/80 p-2 text-slate-400 transition hover:border-slate-700 hover:text-slate-200"
            aria-label="Refresh runtime"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => {
              if (onStop) {
                onStop()
                return
              }
              void runtime.stopCurrentStream()
            }}
            disabled={!stopEnabled || runtime.stoppingSessionId !== null}
            className="rounded-lg border border-rose-500/20 bg-rose-950/15 p-2 text-rose-200 transition hover:border-rose-400/30 hover:bg-rose-950/25 disabled:opacity-60"
            aria-label="Stop active work"
          >
            <Square className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onOpenCommands}
            className="rounded-lg border border-slate-800 bg-slate-950/80 p-2 text-slate-400 transition hover:border-slate-700 hover:text-slate-200"
            aria-label="Open commands"
          >
            <Command className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
