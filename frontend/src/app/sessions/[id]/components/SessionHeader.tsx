'use client'

import { Activity, ArrowLeft, GitBranch, LayoutList, Users } from 'lucide-react'
import Link from 'next/link'
import { type KeyboardEvent, useRef } from 'react'
import type { Session } from '@/lib/api/sessions'
import type { SessionMemoryObservability } from '@/lib/session-memory-observability'
import { cn } from '@/lib/utils'
import {
  formatDurationMs,
  getExecutionIdentity,
  getSessionKindLabel,
  getSessionLastActive,
  getSessionTitle,
} from '../../utils'
import { CopyValueButton } from './CopyValueButton'
import {
  liveActivityLabel,
  modelWasObserved,
  shortSessionId,
} from './session-display'
import { formatDate } from './utils'

export type SessionDetailTab = 'timeline' | 'subagents' | 'info'

const TAB_META: Record<
  SessionDetailTab,
  { label: string; icon: typeof Activity }
> = {
  timeline: { label: 'Timeline', icon: Activity },
  subagents: { label: 'Sub-agents', icon: Users },
  info: { label: 'Info', icon: LayoutList },
}

export function sessionTabId(tab: SessionDetailTab) {
  return `session-tab-${tab}`
}
export function sessionPanelId(tab: SessionDetailTab) {
  return `session-panel-${tab}`
}

interface SessionHeaderProps {
  session: Session
  sessionId: string
  activeTab: SessionDetailTab
  onTabChange: (tab: SessionDetailTab) => void
  /** Tabs to show, in order. Defaults to Timeline and Info. */
  tabs?: SessionDetailTab[]
  /** Parent session when this is a sub-agent; undefined while unknown. */
  parent?: Pick<
    Session,
    'id' | 'title' | 'summary_oneliner' | 'current_branch'
  > | null
  eventsTotal?: number
  maxTurn?: number
  memorySummary?: SessionMemoryObservability | null
  /** True when memorySummary does not cover every memory event. */
  memoryPartial?: boolean
}

function statusTone(status: string) {
  if (status === 'active' || status === 'running')
    return {
      dot: 'bg-emerald-400',
      pill: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200',
    }
  if (status === 'failed' || status === 'error')
    return {
      dot: 'bg-rose-400',
      pill: 'border-rose-500/25 bg-rose-500/10 text-rose-800 dark:text-rose-200',
    }
  return {
    dot: 'bg-slate-500',
    pill: 'border-slate-700/80 bg-slate-900/90 text-slate-300',
  }
}

export function SessionStatusBadge({ status }: { status: string }) {
  const tone = statusTone(status)
  return (
    <span className={cn('page-pill shrink-0', tone.pill)}>
      <span className={cn('h-1.5 w-1.5 rounded-full', tone.dot)} aria-hidden />
      {status}
    </span>
  )
}

function Fact({
  label,
  children,
  className,
}: {
  label: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('page-pill min-w-0 max-w-full', className)}>
      <dt className="shrink-0 text-slate-500">{label}</dt>
      <dd className="min-w-0 truncate">{children}</dd>
    </div>
  )
}

function SessionTabs({
  tabs,
  activeTab,
  onTabChange,
}: {
  tabs: SessionDetailTab[]
  activeTab: SessionDetailTab
  onTabChange: (tab: SessionDetailTab) => void
}) {
  const refs = useRef<Partial<Record<SessionDetailTab, HTMLButtonElement>>>({})

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = tabs.indexOf(activeTab)
    let next: number | null = null
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
    if (event.key === 'ArrowLeft')
      next = (index - 1 + tabs.length) % tabs.length
    if (event.key === 'Home') next = 0
    if (event.key === 'End') next = tabs.length - 1
    if (next === null) return
    event.preventDefault()
    const tab = tabs[next]
    onTabChange(tab)
    refs.current[tab]?.focus()
  }

  return (
    <div
      role="tablist"
      aria-label="Session views"
      className="segmented-control shrink-0 self-start"
      onKeyDown={onKeyDown}
    >
      {tabs.map((tab) => {
        const { label, icon: Icon } = TAB_META[tab]
        const selected = tab === activeTab
        return (
          <button
            key={tab}
            ref={(node) => {
              if (node) refs.current[tab] = node
            }}
            type="button"
            role="tab"
            id={sessionTabId(tab)}
            aria-selected={selected}
            aria-controls={sessionPanelId(tab)}
            tabIndex={selected ? 0 : -1}
            onClick={() => onTabChange(tab)}
            className={cn(
              'segmented-option focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400',
              selected
                ? 'border-amber-500/20 bg-amber-500/10 text-amber-800 dark:text-amber-100'
                : 'hover:border-slate-700/80 hover:bg-slate-900/80 hover:text-slate-200',
            )}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
            {label}
          </button>
        )
      })}
    </div>
  )
}

export function SessionHeader({
  session,
  sessionId,
  activeTab,
  onTabChange,
  tabs = ['timeline', 'info'],
  parent,
  eventsTotal,
  maxTurn,
  memorySummary,
  memoryPartial = false,
}: SessionHeaderProps) {
  const title = getSessionTitle(session)
  const identity = getExecutionIdentity(session)
  const observed = modelWasObserved(session)
  const liveLabel = liveActivityLabel(session.status, session.live_activity)
  const parentId = session.parent_session_id
  const parentLabel = parentId
    ? parent
      ? getSessionTitle(parent)
      : shortSessionId(parentId)
    : null
  const lastActive = getSessionLastActive(session)
  const duration =
    new Date(lastActive).getTime() - new Date(session.created_at).getTime()

  return (
    <header
      className="page-header shrink-0"
      style={{ background: 'var(--card)' }}
    >
      <div className="page-container space-y-2 px-4 py-3 lg:px-8">
        <nav aria-label="Breadcrumb" className="min-w-0">
          <ol className="flex min-w-0 items-center gap-1.5 text-xs text-slate-400">
            <li className="shrink-0">
              <Link
                href="/sessions"
                className="inline-flex items-center gap-1 rounded hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
              >
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
                Sessions
              </Link>
            </li>
            {parentId && (
              <>
                <li aria-hidden className="shrink-0 text-slate-600">
                  ›
                </li>
                <li className="min-w-0 max-w-[40%] shrink truncate">
                  <Link
                    href={`/sessions/${parentId}`}
                    title={parentLabel ?? undefined}
                    className="rounded hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                  >
                    {parentLabel}
                  </Link>
                </li>
              </>
            )}
            <li aria-hidden className="shrink-0 text-slate-600">
              ›
            </li>
            <li
              aria-current="page"
              className="min-w-0 truncate text-slate-300"
              title={title}
            >
              {title}
            </li>
          </ol>
        </nav>

        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex min-w-0 items-start gap-2">
              <h1
                className="page-title line-clamp-2 min-w-0 break-words"
                title={title}
              >
                {title}
              </h1>
              <SessionStatusBadge status={session.status} />
            </div>

            <dl className="page-meta">
              <Fact label="Project">{session.project_id}</Fact>
              {session.current_branch && (
                <Fact label="Branch">
                  <span className="inline-flex items-center gap-1 font-mono">
                    <GitBranch className="h-3 w-3" aria-hidden />
                    {session.current_branch}
                  </span>
                </Fact>
              )}
              <Fact label="Kind">
                {getSessionKindLabel(session.session_type)}
              </Fact>
              <Fact
                label="Model"
                className={cn(
                  identity.fallbackUsed &&
                    'border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-100',
                )}
              >
                <span className="font-mono">
                  {identity.showRequested
                    ? `${identity.requestedModel} → ${identity.effectiveModel}`
                    : identity.effectiveModel}
                  {!observed && ' (delivered model not observed)'}
                </span>
              </Fact>
              <Fact label="Started">
                <time dateTime={session.created_at}>
                  {formatDate(session.created_at)}
                </time>
              </Fact>
              <Fact label="Last active">
                <time dateTime={lastActive}>{formatDate(lastActive)}</time>
              </Fact>
              <Fact label="Duration">{formatDurationMs(duration)}</Fact>
              {eventsTotal !== undefined && (
                <Fact label="Events">
                  <span className="font-mono">
                    {eventsTotal.toLocaleString()}
                  </span>
                </Fact>
              )}
              {maxTurn !== undefined && (
                <Fact label="Turns">
                  <span className="font-mono">{maxTurn}</span>
                </Fact>
              )}
              {memorySummary && (
                <Fact label="Refs">
                  <span className="font-mono">
                    {memorySummary.selectedCount}/{memorySummary.indexCount}{' '}
                    cited {memorySummary.selectedCitedCount}/
                    {memorySummary.selectedCount}
                    {memoryPartial ? ' (loaded only)' : ''}
                  </span>
                </Fact>
              )}
              {liveLabel && (
                <Fact
                  label="Live"
                  className="border-sky-500/20 bg-sky-500/10 text-sky-800 dark:text-sky-100"
                >
                  {liveLabel}
                </Fact>
              )}
            </dl>

            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
              <span className="inline-flex min-w-0 items-center gap-1">
                <span>ID</span>
                <span className="min-w-0 break-all font-mono text-slate-400">
                  {sessionId}
                </span>
                <CopyValueButton value={sessionId} label="Copy session ID" />
              </span>
              {session.external_id && (
                <span className="inline-flex min-w-0 items-center gap-1">
                  <span>Task</span>
                  <span className="min-w-0 break-all font-mono text-slate-400">
                    {session.external_id}
                  </span>
                  <CopyValueButton
                    value={session.external_id}
                    label="Copy task ID"
                  />
                </span>
              )}
            </div>
          </div>

          <SessionTabs
            tabs={tabs}
            activeTab={activeTab}
            onTabChange={onTabChange}
          />
        </div>
      </div>
    </header>
  )
}
