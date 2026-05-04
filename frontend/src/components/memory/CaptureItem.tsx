'use client'

import {
  Bot,
  Bug,
  Eye,
  Layers,
  Lightbulb,
  MessageSquare,
  PenLine,
  RefreshCw,
  Terminal,
  Workflow,
  Zap,
} from 'lucide-react'
import type { CaptureStreamEvent } from '@/hooks/use-memory-stream'
import { formatRelativeTime } from '@/lib/formatters'
import { cn } from '@/lib/utils'

const TYPE_CONFIG: Record<string, { color: string; icon: typeof Eye }> = {
  tool_use: {
    color: 'text-violet-400 bg-violet-400/10 border-violet-400/30',
    icon: Terminal,
  },
  learning: {
    color: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30',
    icon: Lightbulb,
  },
  error: { color: 'text-red-400 bg-red-400/10 border-red-400/30', icon: Bug },
  decision: {
    color: 'text-amber-400 bg-amber-400/10 border-amber-400/30',
    icon: Zap,
  },
  change: {
    color: 'text-amber-400 bg-blue-400/10 border-blue-400/30',
    icon: RefreshCw,
  },
  pattern: {
    color: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/30',
    icon: Layers,
  },
}

const SOURCE_CONFIG: Record<string, { label: string; icon: typeof Eye }> = {
  claude_code: { label: 'Claude Code', icon: Terminal },
  agent_hub_chat: { label: 'Agent Hub', icon: MessageSquare },
  summitflow_task: { label: 'SummitFlow', icon: Workflow },
  agentic: { label: 'Agentic', icon: Bot },
  manual: { label: 'Manual', icon: PenLine },
}

interface CaptureItemProps {
  event: CaptureStreamEvent
}

export function CaptureItem({ event }: CaptureItemProps) {
  const typeConfig = TYPE_CONFIG[event.data.type] || {
    color: 'text-slate-400 bg-slate-400/10 border-slate-400/30',
    icon: Eye,
  }
  const sourceConfig = SOURCE_CONFIG[event.data.source] || {
    label: event.data.source,
    icon: Eye,
  }

  const TypeIcon = typeConfig.icon
  const SourceIcon = sourceConfig.icon

  const dotColor =
    event.event_type === 'observation' ? 'bg-emerald-400' : 'bg-slate-400'

  return (
    <div className="group relative flex gap-3 py-2">
      {/* Status dot */}
      <div className="flex flex-col items-center pt-2 shrink-0">
        <div
          className={cn(
            'w-2.5 h-2.5 rounded-full ring-4 ring-slate-900',
            dotColor,
          )}
        />
      </div>

      {/* Card */}
      <div
        className={cn(
          'flex-1 min-w-0 rounded-lg border border-slate-800/80 bg-slate-900/60 p-3',
          'hover:bg-slate-800/60 hover:border-slate-700/80 transition-colors',
        )}
      >
        {/* Header row */}
        <div className="flex items-start justify-between gap-3 mb-1.5">
          <div className="flex items-center gap-2 min-w-0 flex-wrap">
            {/* Source badge */}
            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full bg-slate-800 text-slate-300 border border-slate-700/60">
              <SourceIcon className="h-3 w-3" />
              {sourceConfig.label}
            </span>
            {/* Type badge */}
            <span
              className={cn(
                'inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full border',
                typeConfig.color,
              )}
            >
              <TypeIcon className="h-3 w-3" />
              {event.data.type}
            </span>
          </div>
          <span className="text-[11px] text-slate-500 shrink-0">
            {formatRelativeTime(event.timestamp)}
          </span>
        </div>

        {/* Title */}
        <p className="text-sm font-medium text-slate-200 truncate">
          {event.data.title}
        </p>

        {/* Content preview */}
        {event.data.content && (
          <p className="mt-1 text-xs text-slate-400 leading-relaxed line-clamp-2">
            {event.data.content}
          </p>
        )}

        {/* Footer */}
        {event.data.session_id && (
          <div className="mt-2 text-[10px] text-slate-600">
            session: {event.data.session_id.slice(0, 8)}
          </div>
        )}
      </div>
    </div>
  )
}
