'use client'

import { RefreshCw } from 'lucide-react'
import {
  memo,
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { SessionListItem } from '@/lib/api/sessions'
import { cn } from '@/lib/utils'
import { StatusCell } from '../components/StatusCell'
import { useSessionChildren, useSessionLog } from '../hooks/useSessionLog'
import { formatDurationMs, getSessionTitle, getUsageSummary } from '../utils'
import { buildLogEntries, type LogDetail, type LogEntry } from './entries'
import { interleave } from './interleave'

export const CHILD_BATCH_PAGE = 25

function clock(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function absolute(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

const LABEL_TONE: Record<string, string> = {
  prompt: 'text-sky-700 dark:text-sky-300',
  agent: 'text-violet-700 dark:text-violet-300',
  context: 'text-slate-500',
  tool: 'text-slate-400',
  error: 'text-rose-700 dark:text-rose-300',
  thinking: 'text-amber-700 dark:text-amber-300/80',
  usage: 'text-slate-500',
  memory: 'text-emerald-700 dark:text-emerald-300/80',
}

function MetaText({ meta, failed }: { meta?: string; failed?: boolean }) {
  if (!meta) return null
  const parts = meta.split(/(\+\d+|−\d+|exit \d+)/)
  return (
    <span className="whitespace-nowrap text-slate-500">
      {parts.map((part, index) => {
        const key = `${index}:${part}`
        if (/^\+\d+$/.test(part))
          return (
            <span key={key} className="text-emerald-700 dark:text-emerald-300">
              {part}
            </span>
          )
        if (/^−\d+$/.test(part))
          return (
            <span key={key} className="text-rose-700 dark:text-rose-300">
              {part}
            </span>
          )
        if (/^exit \d+$/.test(part))
          return (
            <span
              key={key}
              className={
                part === 'exit 0' && !failed
                  ? 'text-emerald-700 dark:text-emerald-300/90'
                  : 'text-rose-700 dark:text-rose-300'
              }
            >
              {part}
            </span>
          )
        return <span key={key}>{part}</span>
      })}
    </span>
  )
}

function DetailBlock({ detail }: { detail: LogDetail }) {
  if (detail.type === 'diff') {
    return (
      <pre className="overflow-x-auto py-1">
        {detail.lines.map((line, index) => (
          <span
            key={index}
            className={cn(
              'block px-2',
              line.startsWith('+') &&
                'bg-emerald-500/10 text-emerald-800 dark:text-emerald-200',
              line.startsWith('-') &&
                'bg-rose-500/10 text-rose-700 dark:text-rose-200',
            )}
          >
            {line || ' '}
          </span>
        ))}
      </pre>
    )
  }
  return (
    <>
      {detail.type === 'output' && detail.truncated ? (
        <div className="border-b border-slate-800 px-2 py-0.5 text-[11px] text-slate-500">
          last 40 lines
        </div>
      ) : null}
      <pre className="whitespace-pre-wrap break-words px-2 py-1">
        {detail.text}
      </pre>
    </>
  )
}

const LogRow = memo(function LogRow({
  entry,
  open,
  raw,
  onToggle,
}: {
  entry: LogEntry
  open: boolean
  raw: boolean
  onToggle: (id: string) => void
}) {
  const expandable = raw || !!entry.detail
  return (
    <div data-testid="log-row" data-kind={entry.kind}>
      <button
        type="button"
        aria-expanded={expandable ? open : undefined}
        disabled={!expandable}
        onClick={() => onToggle(entry.id)}
        title={absolute(entry.at)}
        className={cn(
          'grid w-full grid-cols-[4.25rem_minmax(0,1fr)] items-baseline gap-x-2 rounded px-1.5 py-[3px] text-left font-mono text-[12px] leading-5 sm:grid-cols-[4.25rem_4.75rem_minmax(0,1fr)_auto]',
          expandable ? 'cursor-pointer hover:bg-slate-900' : 'cursor-default',
          entry.failed && 'bg-rose-500/[0.07]',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-400/50',
        )}
      >
        <span className="hidden text-slate-600 sm:block">
          {clock(entry.at)}
        </span>
        <span
          className={cn(
            'truncate',
            entry.failed
              ? 'text-rose-700 dark:text-rose-300'
              : LABEL_TONE[entry.kind],
          )}
        >
          {entry.label}
        </span>
        <span
          className={cn(
            'min-w-0',
            open ? 'whitespace-pre-wrap break-words' : 'truncate',
            entry.kind === 'prompt' ? 'text-slate-100' : 'text-slate-300',
            entry.kind === 'context' && 'text-slate-500',
          )}
        >
          {entry.summary}
        </span>
        <span className="col-start-2 sm:col-start-auto">
          <MetaText meta={entry.meta} failed={entry.failed} />
        </span>
      </button>
      {open ? (
        <div className="mb-1 ml-1.5 max-h-80 overflow-auto rounded border border-slate-800 bg-slate-950 font-mono text-[11.5px] text-slate-300 sm:ml-[9.5rem]">
          {raw ? (
            <pre className="whitespace-pre-wrap break-words px-2 py-1">
              {JSON.stringify(entry.raw, null, 2)}
            </pre>
          ) : entry.detail ? (
            <DetailBlock detail={entry.detail} />
          ) : null}
        </div>
      ) : null}
    </div>
  )
})

function childMeta(child: SessionListItem): string {
  const last = child.last_active_at ?? child.updated_at
  const ms = new Date(last).getTime() - new Date(child.created_at).getTime()
  const usage = getUsageSummary(child)
  return [
    Number.isFinite(ms) && ms >= 0 ? formatDurationMs(ms) : null,
    usage.known ? `${usage.label} tokens` : null,
  ]
    .filter(Boolean)
    .join(' · ')
}

function ChildRow({
  child,
  depth,
  raw,
  details,
  onSelect,
}: {
  child: SessionListItem
  depth: number
  raw: boolean
  details: boolean
  onSelect: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const nestable = depth === 0
  const title = getSessionTitle(child)
  return (
    <div data-testid="log-child">
      <button
        type="button"
        aria-expanded={nestable ? open : undefined}
        onClick={() =>
          nestable ? setOpen((value) => !value) : onSelect(child.id)
        }
        className="grid w-full grid-cols-[4.25rem_minmax(0,1fr)] items-baseline gap-x-2 rounded px-1.5 py-[3px] text-left font-mono text-[12px] leading-5 hover:bg-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-400/50 sm:grid-cols-[4.25rem_4.75rem_minmax(0,1fr)_auto]"
        title={
          nestable
            ? `Started ${absolute(child.created_at)}`
            : 'Open this sub-agent'
        }
      >
        <span className="hidden text-slate-600 sm:block">
          {clock(child.created_at)}
        </span>
        <span className="text-cyan-700 dark:text-cyan-300">
          {nestable ? (open ? '▾ ' : '▸ ') : '↗ '}sub-agent
        </span>
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="truncate text-slate-100">{title}</span>
          <StatusCell
            status={child.status}
            liveActivity={child.live_activity}
            showLabel
          />
        </span>
        <span className="col-start-2 whitespace-nowrap text-slate-500 sm:col-start-auto">
          {childMeta(child)}
        </span>
      </button>
      {open ? (
        <div className="mb-1 ml-3 border-l-2 border-slate-700/80 pl-2 sm:ml-[9.5rem]">
          <SessionLog
            sessionId={child.id}
            childCount={child.child_session_count ?? 0}
            activeChildren={child.active_child_session_count ?? 0}
            live={child.status === 'active' || child.status === 'running'}
            details={details}
            raw={raw}
            search=""
            depth={depth + 1}
            onSelect={onSelect}
          />
        </div>
      ) : null}
    </div>
  )
}

function ChildBatch({
  childrenList,
  depth,
  raw,
  details,
  onSelect,
}: {
  childrenList: SessionListItem[]
  depth: number
  raw: boolean
  details: boolean
  onSelect: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [shown, setShown] = useState(CHILD_BATCH_PAGE)
  const counts = useMemo(() => {
    const byStatus = new Map<string, number>()
    for (const child of childrenList)
      byStatus.set(child.status, (byStatus.get(child.status) ?? 0) + 1)
    return [...byStatus.entries()]
      .map(([status, n]) => `${n} ${status}`)
      .join(', ')
  }, [childrenList])

  if (childrenList.length === 1)
    return (
      <ChildRow
        child={childrenList[0]}
        depth={depth}
        raw={raw}
        details={details}
        onSelect={onSelect}
      />
    )

  const names = childrenList
    .slice(0, 2)
    .map((child) => getSessionTitle(child))
    .join(', ')
  return (
    <div
      data-testid="log-child-batch"
      className="my-0.5 rounded border border-dashed border-slate-800"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="grid w-full grid-cols-[4.25rem_minmax(0,1fr)] items-baseline gap-x-2 rounded px-1.5 py-[3px] text-left font-mono text-[12px] leading-5 hover:bg-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-400/50 sm:grid-cols-[4.25rem_4.75rem_minmax(0,1fr)_auto]"
      >
        <span className="hidden text-slate-600 sm:block">
          {clock(childrenList[0].created_at)}
        </span>
        <span className="text-cyan-700 dark:text-cyan-300">
          {open ? '▾ ' : '▸ '}started
        </span>
        <span className="truncate text-slate-200">
          {childrenList.length} sub-agents
          <span className="text-slate-500">
            {' '}
            · {names}
            {childrenList.length > 2 ? `, +${childrenList.length - 2}` : ''}
          </span>
        </span>
        <span className="col-start-2 whitespace-nowrap text-slate-500 sm:col-start-auto">
          {counts}
        </span>
      </button>
      {open ? (
        <div className="pb-1 pl-2">
          {childrenList.slice(0, shown).map((child) => (
            <ChildRow
              key={child.id}
              child={child}
              depth={depth}
              raw={raw}
              details={details}
              onSelect={onSelect}
            />
          ))}
          {childrenList.length > shown ? (
            <button
              type="button"
              onClick={() => setShown((value) => value + CHILD_BATCH_PAGE)}
              className="ml-1.5 mt-1 rounded border border-slate-800 px-2 py-0.5 font-mono text-[12px] text-sky-700 dark:text-sky-300 hover:bg-slate-900"
            >
              Show {Math.min(CHILD_BATCH_PAGE, childrenList.length - shown)}{' '}
              more of {childrenList.length - shown}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function Note({
  children,
  tone = 'muted',
}: {
  children: React.ReactNode
  tone?: 'muted' | 'error'
}) {
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-2 px-1.5 py-1.5 text-[12px]',
        tone === 'error'
          ? 'text-rose-700 dark:text-rose-200'
          : 'text-slate-500',
      )}
    >
      {children}
    </div>
  )
}

/**
 * Dense, one-line-per-event log of a session. Top level (depth 0) nests each
 * sub-agent's own log in place; deeper sub-agents open as their own selection.
 */
export function SessionLog({
  sessionId,
  childCount,
  activeChildren = 0,
  live,
  details,
  raw,
  search,
  depth = 0,
  scrollRef,
  onSelect,
}: {
  sessionId: string
  childCount: number
  activeChildren?: number
  live: boolean
  details: boolean
  raw: boolean
  search: string
  depth?: number
  /** Scroll container that should start at the newest entry (top level only). */
  scrollRef?: React.RefObject<HTMLDivElement | null>
  onSelect: (id: string) => void
}) {
  const log = useSessionLog(sessionId, { details, search, live })
  const children = useSessionChildren(sessionId, childCount, activeChildren)
  const [open, setOpen] = useState<Set<string>>(() => new Set())

  const entries = useMemo(
    () =>
      buildLogEntries(log.events, {
        fromStart: !log.hasEarlier && !log.appliedSearch,
      }),
    [log.events, log.hasEarlier, log.appliedSearch],
  )
  const childList = children.data?.children ?? []
  const searching = log.appliedSearch.length > 0
  const { items, heldBack } = useMemo(
    () => interleave(entries, searching ? [] : childList, log.hasEarlier),
    [entries, childList, searching, log.hasEarlier],
  )

  const toggle = useCallback((id: string) => {
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  // Keep the reader's place: start at the newest entry, follow new entries
  // only while already at the bottom, and hold position when older ones load.
  const anchor = useRef<{
    height: number
    top: number
    atBottom: boolean
  } | null>(null)
  const startedAtBottom = useRef(false)
  const captureScroll = useCallback(() => {
    const node = scrollRef?.current
    if (!node) return
    anchor.current = {
      height: node.scrollHeight,
      top: node.scrollTop,
      atBottom: node.scrollHeight - node.scrollTop - node.clientHeight < 40,
    }
  }, [scrollRef])
  const loadEarlier = useCallback(() => {
    captureScroll()
    if (anchor.current) anchor.current.atBottom = false
    log.loadEarlier()
  }, [captureScroll, log])

  useLayoutEffect(() => {
    const node = scrollRef?.current
    if (!node || !log.hasData) return
    if (!startedAtBottom.current) {
      startedAtBottom.current = true
      node.scrollTop = node.scrollHeight
      return
    }
    const previous = anchor.current
    if (previous?.atBottom) node.scrollTop = node.scrollHeight
    else if (
      previous &&
      previous.height !== node.scrollHeight &&
      previous.top < 80
    )
      node.scrollTop = previous.top + (node.scrollHeight - previous.height)
    anchor.current = null
  }, [items.length, log.hasData])

  // Before a live refetch lands, note whether the reader is at the bottom.
  useLayoutEffect(() => {
    const node = scrollRef?.current
    if (!node) return
    const onScroll = () => captureScroll()
    node.addEventListener('scroll', onScroll, { passive: true })
    return () => node.removeEventListener('scroll', onScroll)
  }, [scrollRef, captureScroll])

  const loaded = log.events.length
  const remaining = log.total !== null ? Math.max(0, log.total - loaded) : null

  return (
    <div
      data-testid={depth === 0 ? 'session-log' : 'session-log-nested'}
      className="py-1"
    >
      {log.error && !log.hasData ? (
        <Note tone="error">
          <span>The log failed to load.</span>
          <button
            type="button"
            onClick={() => void log.refetch()}
            className="inline-flex items-center gap-1 rounded border border-rose-400/30 px-2 py-0.5 hover:bg-rose-500/10"
          >
            <RefreshCw className="h-3 w-3" />
            Retry
          </button>
        </Note>
      ) : null}
      {log.isLoading ? <Note>Loading log…</Note> : null}

      {log.hasEarlier || heldBack > 0 ? (
        <Note>
          <button
            type="button"
            onClick={loadEarlier}
            disabled={log.loadingEarlier || !log.hasEarlier}
            className="rounded border border-slate-800 px-2 py-0.5 font-mono text-sky-700 dark:text-sky-300 hover:bg-slate-900 disabled:text-slate-500"
          >
            {log.loadingEarlier ? 'Loading…' : 'Load earlier'}
          </button>
          <span>
            {remaining !== null
              ? `${remaining.toLocaleString()} earlier events`
              : 'Earlier events'}
            {heldBack > 0 ? ` · ${heldBack} sub-agents started earlier` : ''}
          </span>
          {log.loadEarlierFailed ? (
            <span className="text-rose-700 dark:text-rose-300">
              Loading failed; try again.
            </span>
          ) : null}
        </Note>
      ) : null}

      {items.map((item) => {
        if (item.type === 'turn')
          return (
            <div
              key={item.key}
              className="mt-1.5 flex items-center gap-2 px-1.5 font-mono text-[11px] text-slate-600 first:mt-0"
            >
              <span>turn {item.turn}</span>
              <span className="h-px flex-1 bg-slate-800/80" />
            </div>
          )
        if (item.type === 'children')
          return (
            <ChildBatch
              key={item.key}
              childrenList={item.children}
              depth={depth}
              raw={raw}
              details={details}
              onSelect={onSelect}
            />
          )
        return (
          <LogRow
            key={item.key}
            entry={item.entry}
            open={open.has(item.entry.id)}
            raw={raw}
            onToggle={toggle}
          />
        )
      })}

      {log.hasData && !log.isLoading && items.length === 0 ? (
        <Note>
          {searching
            ? `Nothing in this session matches “${log.appliedSearch}”.`
            : details
              ? 'No events recorded.'
              : 'No messages or tool calls recorded. Details may show thinking or usage.'}
        </Note>
      ) : null}
      {children.error ? (
        <Note tone="error">Sub-agents failed to load.</Note>
      ) : null}
      {children.data && !children.data.complete ? (
        <Note>
          Showing {children.data.children.length} of {children.data.total}{' '}
          sub-agents.
        </Note>
      ) : null}
      {log.refreshing ? <Note>Updating…</Note> : null}
    </div>
  )
}
