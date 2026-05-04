import { MessageSquare } from 'lucide-react'
import type { SessionListItem } from '@/lib/api'
import { formatModelName, formatRelativeTime } from '@/lib/formatters'
import { cn } from '@/lib/utils'

// ─────────────────────────────────────────────────────────────────────────────
// SESSIONS TAB CONTENT
// ─────────────────────────────────────────────────────────────────────────────

export function SessionsTabContent({
  sessions,
  isLoading,
}: {
  sessions: SessionListItem[]
  isLoading: boolean
}) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-12 bg-slate-800 rounded animate-pulse" />
        ))}
      </div>
    )
  }

  if (sessions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-slate-400">
        <MessageSquare className="h-8 w-8 mb-2 opacity-50" />
        <p className="text-sm">No recent sessions</p>
      </div>
    )
  }

  return (
    <div className="space-y-1">
      {sessions.slice(0, 6).map((session) => (
        <a
          key={session.id}
          href={`/sessions/${session.id}`}
          className="flex items-center justify-between p-2.5 rounded-md hover:bg-slate-800/50 transition-colors group"
        >
          <div className="flex items-center gap-3 min-w-0">
            <div
              className={cn(
                'w-1.5 h-1.5 rounded-full',
                session.status === 'active'
                  ? 'bg-emerald-500 animate-pulse'
                  : 'bg-slate-400',
              )}
            />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-slate-100 truncate">
                  {session.project_id}
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-500">
                  {formatModelName(session.model, 12)}
                </span>
              </div>
              <div className="text-[11px] text-slate-400">
                {session.message_count} messages
                {session.agent_slug && (
                  <span className="ml-2 text-slate-500">
                    | {session.agent_slug}
                  </span>
                )}
              </div>
            </div>
          </div>
          <span className="text-[10px] font-mono text-slate-400 group-hover:text-slate-300">
            {formatRelativeTime(session.created_at)}
          </span>
        </a>
      ))}
    </div>
  )
}
