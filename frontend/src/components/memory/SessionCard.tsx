'use client'

import {
  Bot,
  ChevronDown,
  ChevronUp,
  Clock,
  Eye,
  FolderOpen,
  MessageCircle,
} from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'

export interface SessionMemoryInfo {
  session_id: string
  agent_slug: string | null
  project_id: string | null
  started_at: string
  ended_at: string | null
  episodes_loaded: number
  episodes_cited: number
  citation_rate: number
  source: string | null
}

const SOURCE_STYLES: Record<
  string,
  { label: string; bg: string; text: string }
> = {
  claude_code: {
    label: 'Claude Code',
    bg: 'bg-violet-500/15',
    text: 'text-violet-400',
  },
  completion: {
    label: 'Completion',
    bg: 'bg-blue-500/15',
    text: 'text-amber-400',
  },
  chat: { label: 'Chat', bg: 'bg-emerald-500/15', text: 'text-emerald-400' },
  agent: { label: 'Agent', bg: 'bg-amber-500/15', text: 'text-amber-400' },
  roundtable: {
    label: 'Roundtable',
    bg: 'bg-pink-500/15',
    text: 'text-pink-400',
  },
  image_generation: {
    label: 'Image Gen',
    bg: 'bg-cyan-500/15',
    text: 'text-cyan-400',
  },
}

function getSourceStyle(source: string | null) {
  if (!source)
    return { label: 'Unknown', bg: 'bg-slate-500/15', text: 'text-slate-400' }
  return (
    SOURCE_STYLES[source] || {
      label: source,
      bg: 'bg-slate-500/15',
      text: 'text-slate-400',
    }
  )
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDuration(startStr: string, endStr: string | null): string {
  if (!endStr) return 'active'
  const start = new Date(startStr).getTime()
  const end = new Date(endStr).getTime()
  const diffMs = end - start
  if (diffMs < 1000) return '<1s'
  if (diffMs < 60000) return `${Math.floor(diffMs / 1000)}s`
  if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m`
  return `${Math.floor(diffMs / 3600000)}h ${Math.floor((diffMs % 3600000) / 60000)}m`
}

function getCitationColor(rate: number): string {
  if (rate >= 0.5) return 'text-emerald-400'
  if (rate >= 0.2) return 'text-amber-400'
  return 'text-slate-400'
}

interface SessionCardProps {
  session: SessionMemoryInfo
}

export function SessionCard({ session }: SessionCardProps) {
  const [expanded, setExpanded] = useState(false)
  const sourceStyle = getSourceStyle(session.source)

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 hover:border-slate-700 transition-colors">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left p-4"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-2">
              {session.agent_slug && (
                <span className="flex items-center gap-1.5 text-sm font-medium text-slate-100">
                  <Bot className="h-3.5 w-3.5 text-slate-400" />
                  {session.agent_slug}
                </span>
              )}
              {session.project_id && (
                <span className="flex items-center gap-1.5 text-xs text-slate-400">
                  <FolderOpen className="h-3 w-3" />
                  {session.project_id}
                </span>
              )}
              <span
                className={cn(
                  'px-2 py-0.5 rounded-full text-xs font-medium',
                  sourceStyle.bg,
                  sourceStyle.text,
                )}
              >
                {sourceStyle.label}
              </span>
            </div>

            <div className="flex items-center gap-4 text-xs text-slate-400">
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {formatDate(session.started_at)}
              </span>
              <span>
                {formatDuration(session.started_at, session.ended_at)}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-4 flex-shrink-0">
            <div className="flex items-center gap-3 text-xs">
              <span
                className="flex items-center gap-1 text-slate-300"
                title="Episodes loaded"
              >
                <Eye className="h-3.5 w-3.5 text-slate-400" />
                {session.episodes_loaded}
              </span>
              <span
                className="flex items-center gap-1 text-slate-300"
                title="Episodes cited"
              >
                <MessageCircle className="h-3.5 w-3.5 text-slate-400" />
                {session.episodes_cited}
              </span>
              <span
                className={cn(
                  'font-medium tabular-nums',
                  getCitationColor(session.citation_rate),
                )}
                title="Citation rate"
              >
                {(session.citation_rate * 100).toFixed(0)}%
              </span>
            </div>
            {expanded ? (
              <ChevronUp className="h-4 w-4 text-slate-500" />
            ) : (
              <ChevronDown className="h-4 w-4 text-slate-500" />
            )}
          </div>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-slate-800 pt-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-md bg-slate-800/60 p-3">
              <div className="text-xs text-slate-500 mb-1">Session ID</div>
              <div className="text-xs text-slate-300 font-mono truncate">
                {session.session_id}
              </div>
            </div>
            <div className="rounded-md bg-slate-800/60 p-3">
              <div className="text-xs text-slate-500 mb-1">Episodes Loaded</div>
              <div className="text-lg font-semibold text-slate-100">
                {session.episodes_loaded}
              </div>
            </div>
            <div className="rounded-md bg-slate-800/60 p-3">
              <div className="text-xs text-slate-500 mb-1">Episodes Cited</div>
              <div className="text-lg font-semibold text-slate-100">
                {session.episodes_cited}
              </div>
            </div>
            <div className="rounded-md bg-slate-800/60 p-3">
              <div className="text-xs text-slate-500 mb-1">Citation Rate</div>
              <div
                className={cn(
                  'text-lg font-semibold',
                  getCitationColor(session.citation_rate),
                )}
              >
                {(session.citation_rate * 100).toFixed(1)}%
              </div>
            </div>
          </div>
          {session.ended_at && (
            <div className="mt-3 text-xs text-slate-500">
              Ended: {formatDate(session.ended_at)}
            </div>
          )}
          {!session.ended_at && (
            <div className="mt-3 flex items-center gap-1.5 text-xs text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Session active
            </div>
          )}
        </div>
      )}
    </div>
  )
}
