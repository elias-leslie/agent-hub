'use client'

import { ChevronDown, ChevronRight, Clock, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { CodeBlock } from '@/components/output/code-block'
import type { SessionTimelineEvent } from '@/lib/api'
import type { NativeCommandEvidence } from '@/lib/api/native-evidence'
import { cn } from '@/lib/utils'
import { getEventConfig } from './event-config'
import { formatDuration, formatTimestamp, formatTokens } from './timeline-utils'

interface EventItemProps {
  event: SessionTimelineEvent
  isFirst: boolean
  isLast: boolean
  nativeCommands?: NativeCommandEvidence[]
}

export function EventItem({
  event,
  isFirst,
  isLast,
  nativeCommands,
}: EventItemProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const config = getEventConfig(event.event_type)
  const Icon = config.icon

  const hasExpandableContent =
    (event.content && event.content.length > 200) ||
    event.tool_input ||
    event.tool_output

  const truncatedContent = event.content
    ? event.content.length > 200 && !isExpanded
      ? `${event.content.slice(0, 200)}...`
      : event.content
    : null

  return (
    <div className="relative flex gap-3 group">
      {/* Timeline connector */}
      <div className="relative flex flex-col items-center">
        {/* Top line */}
        {!isFirst && (
          <div
            className={cn(
              'absolute top-0 w-px h-3',
              'bg-gradient-to-b from-slate-700/60 to-slate-700/30',
            )}
          />
        )}

        {/* Icon circle */}
        <div
          className={cn(
            'relative z-10 mt-3 flex items-center justify-center',
            'w-8 h-8 rounded-lg',
            config.bgColor,
            'border',
            config.borderColor,
            'shadow-lg',
            config.glowColor,
            'transition-all duration-200',
            'group-hover:scale-110',
          )}
        >
          <Icon className={cn('w-4 h-4', config.color)} />
        </div>

        {/* Bottom line */}
        {!isLast && (
          <div
            className={cn(
              'flex-1 w-px min-h-[2rem]',
              'bg-gradient-to-b from-slate-700/30 to-slate-700/60',
            )}
          />
        )}
      </div>

      {/* Event content */}
      <div className="flex-1 pb-4 min-w-0">
        <div
          className={cn(
            'rounded-lg border p-3',
            config.bgColor,
            config.borderColor,
            'shadow-lg',
            config.glowColor,
            'transition-all duration-200',
            isExpanded && 'ring-1 ring-white/5',
          )}
        >
          {/* Header row */}
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
            <div className="flex flex-wrap items-center gap-2 min-w-0">
              <span
                className={cn(
                  'text-sm font-semibold tracking-wide',
                  config.color,
                )}
              >
                {config.label}
              </span>

              {event.tool_name && (
                <span className="px-2 py-0.5 rounded bg-slate-800/60 text-xs font-mono text-slate-300 truncate max-w-[200px]">
                  {event.tool_name}
                </span>
              )}

              {event.agent_name && (
                <span className="px-2 py-0.5 rounded bg-slate-800/60 text-xs text-slate-400">
                  {event.agent_name}
                </span>
              )}

              {event.model_used && (
                <span className="px-2 py-0.5 rounded bg-indigo-900/30 text-xs font-mono text-indigo-400/70 truncate max-w-[160px]">
                  {event.model_used}
                </span>
              )}
            </div>

            <div className="flex items-center gap-3 text-xs text-slate-500 shrink-0">
              {event.tokens !== null && (
                <span className="flex items-center gap-1 font-mono">
                  <Sparkles className="w-3 h-3" />
                  {formatTokens(event.tokens)}
                </span>
              )}

              {event.duration_ms !== null && (
                <span className="flex items-center gap-1 font-mono">
                  <Clock className="w-3 h-3" />
                  {formatDuration(event.duration_ms)}
                </span>
              )}

              <span className="font-mono tabular-nums">
                {formatTimestamp(event.created_at)}
              </span>

              {hasExpandableContent && (
                <button
                  type="button"
                  aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${config.label} details`}
                  aria-expanded={isExpanded}
                  onClick={() => setIsExpanded(!isExpanded)}
                  className="rounded p-1 text-slate-400 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                >
                  {isExpanded ? (
                    <ChevronDown className="w-4 h-4" />
                  ) : (
                    <ChevronRight className="w-4 h-4" />
                  )}
                </button>
              )}
            </div>
          </div>

          {/* Content */}
          {truncatedContent && (
            <div
              className={cn(
                'text-sm text-slate-300 whitespace-pre-wrap break-words',
                'font-mono leading-relaxed',
                event.event_type === 'thinking' && 'italic text-amber-200/80',
              )}
            >
              {truncatedContent}
            </div>
          )}

          {/* Expanded tool details */}
          {isExpanded && (event.tool_input || event.tool_output) && (
            <div className="mt-3 space-y-3">
              {event.tool_input && (
                <div>
                  <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                    Input
                  </div>
                  <CodeBlock
                    code={JSON.stringify(event.tool_input, null, 2)}
                    language="json"
                    maxHeight={300}
                    showLineNumbers={false}
                  />
                </div>
              )}

              {event.tool_output && (
                <div>
                  <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                    Output
                  </div>
                  <CodeBlock
                    code={
                      typeof event.tool_output === 'string'
                        ? event.tool_output
                        : JSON.stringify(event.tool_output, null, 2)
                    }
                    language="json"
                    maxHeight={300}
                    showLineNumbers={false}
                  />
                </div>
              )}
            </div>
          )}
          {!!nativeCommands?.length && (
            <details className="mt-3 border-t border-slate-800/60 pt-2 text-xs text-card-foreground">
              <summary className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
                Canonical command provenance
              </summary>
              <div className="mt-2 space-y-3">
                {nativeCommands.map((command) => (
                  <div key={command.entity_id}>
                    <p className="break-all">
                      Entity {command.entity_id} ·{' '}
                      {command.status.replaceAll('_', ' ')} · Observed delivered
                      model {command.observed_model || 'unknown'}
                    </p>
                    <p className="mt-1">
                      {command.projection_event_ids.length} timeline projections
                      refer to this entity. Source receipts below are evidence
                      for the same work.
                    </p>
                    <ul className="mt-2 space-y-1">
                      {command.receipts.map((receipt) => (
                        <li
                          key={`${receipt.source_id}:${receipt.position}`}
                          className="break-all"
                        >
                          {receipt.source_kind === 'app_server'
                            ? 'Managed App Server'
                            : 'Rollout'}{' '}
                          ·{' '}
                          {receipt.origin?.replaceAll('_', ' ') ||
                            'origin unknown'}{' '}
                          ·{' '}
                          {receipt.authenticity === 'local_verified'
                            ? 'locally verified'
                            : 'collector attested'}{' '}
                          · {receipt.disposition.replaceAll('_', ' ')} · Source{' '}
                          {receipt.source_id}, position {receipt.position}
                        </li>
                      ))}
                    </ul>
                    {command.receipts.length === 0 && (
                      <p className="mt-2">
                        Source receipts are unavailable in loaded provenance.
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      </div>
    </div>
  )
}
