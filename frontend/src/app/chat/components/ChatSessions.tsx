'use client'

import { describePhase } from '@agent-hub/chat-ui'
import { RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { agentHubClient } from '@/lib/agent-hub-client'
import { cn } from '@/lib/utils'

const POLL_MS = 5000
const PAGE_SIZE = 15

export interface ChatSessionRow {
  id: string
  title: string
  agentSlug: string | null
  running: boolean
  phase: string | null
  updatedAt: string | null
}

function toRow(session: {
  id: string
  title?: string | null
  summary_oneliner?: string | null
  agent_slug?: string | null
  turn_state?: 'running' | 'idle'
  turn_phase?: string | null
  last_active_at?: string | null
  updated_at: string
}): ChatSessionRow {
  return {
    id: session.id,
    title:
      session.title ||
      session.summary_oneliner ||
      `session ${session.id.slice(0, 8)}`,
    agentSlug: session.agent_slug ?? null,
    running: session.turn_state === 'running',
    phase: session.turn_phase ?? null,
    updatedAt: session.last_active_at ?? session.updated_at,
  }
}

function ago(iso: string | null): string {
  if (!iso) return ''
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 90) return 'now'
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 129600) return `${Math.round(seconds / 3600)}h ago`
  return `${Math.round(seconds / 86400)}d ago`
}

export function ChatSessions({
  activeSessionId,
  onSelect,
}: {
  activeSessionId: string | null
  onSelect: (session: ChatSessionRow) => void
}) {
  const [rows, setRows] = useState<ChatSessionRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const page = await agentHubClient.sessions.list({
        kind: 'chat',
        page_size: PAGE_SIZE,
      })
      setRows(page.sessions.map(toRow))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed')
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load()
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [load])

  const running = rows?.filter((row) => row.running).length ?? 0

  return (
    <section
      className="rounded-lg border border-border bg-card/65 p-3"
      aria-label="Chat sessions"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Sessions{running > 0 ? ` · ${running} running` : ''}
        </h2>
        <button
          type="button"
          onClick={() => void load()}
          aria-label="Refresh sessions"
          title="Refresh sessions"
          className="rounded p-1 text-muted-foreground transition hover:bg-accent hover:text-accent-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      {error ? (
        <p className="mt-2 text-xs text-destructive" role="alert">
          {rows
            ? `Showing an older list; refresh failed: ${error}`
            : `Could not load sessions: ${error}`}
        </p>
      ) : null}

      {rows === null && !error ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Loading sessions...
        </p>
      ) : null}

      {rows && rows.length === 0 ? (
        <p className="mt-2 text-xs text-muted-foreground">
          No chat sessions yet.
        </p>
      ) : null}

      {rows && rows.length > 0 ? (
        <ul className="mt-2 max-h-64 space-y-1 overflow-y-auto">
          {rows.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                onClick={() => onSelect(row)}
                aria-current={row.id === activeSessionId ? 'true' : undefined}
                className={cn(
                  'w-full rounded-md px-2 py-1.5 text-left text-xs transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring',
                  row.id === activeSessionId
                    ? 'bg-accent text-accent-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                )}
              >
                <span className="block truncate font-medium text-foreground">
                  {row.title}
                </span>
                <span className="flex items-center gap-1.5 truncate text-[11px]">
                  {row.running ? (
                    <span
                      className="inline-flex items-center gap-1 text-amber-300"
                      title="A turn is running on the server"
                    >
                      <span
                        aria-hidden="true"
                        className="h-1.5 w-1.5 rounded-full bg-amber-300"
                      />
                      {describePhase(row.phase) ?? 'Turn running'}
                    </span>
                  ) : null}
                  {row.agentSlug ? <span>{row.agentSlug}</span> : null}
                  <span>{ago(row.updatedAt)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
