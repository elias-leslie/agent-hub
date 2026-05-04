'use client'

import { useState } from 'react'
import {
  formatTimeLabel,
  formatTimestampTitle,
  prettifyDisplayText,
  shortenText,
} from './workspace-format'

// Re-export all classification helpers
export {
  badgeToneClasses,
  compactPath,
  entryStatusClasses,
  eventAccentClasses,
  eventLabel,
  eventSummaryLabel,
  eventToneClasses,
  heartbeatIsImportant,
  humanizeFieldLabel,
  isGenericStatusText,
  isNearBottom,
  isPromptLikeText,
  isRecord,
  outcomeToneClasses,
  rootCauseClasses,
  shouldRenderPulseSummary,
} from './workspace-classify'
// Re-export all formatting and text processing helpers
export {
  addUniqueText,
  extractWrappedTextPayload,
  formatDayLabel,
  formatDurationLabel,
  formatRuntimeLabel,
  formatTimeLabel,
  formatTimestampTitle,
  humanizeTaskContextText,
  normalizeText,
  prettifyDisplayText,
  shortenText,
  unescapeDisplayText,
} from './workspace-format'

// --- Small UI components ---

export function DateDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-4 py-4">
      <div className="h-px flex-1 bg-gradient-to-r from-transparent via-slate-800 to-slate-800" />
      <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500 select-none">
        {label}
      </span>
      <div className="h-px flex-1 bg-gradient-to-l from-transparent via-slate-800 to-slate-800" />
    </div>
  )
}

export function TimelineTimestamp({ timestamp }: { timestamp: Date }) {
  const label = formatTimeLabel(timestamp)
  const title = formatTimestampTitle(timestamp)
  return (
    <time
      dateTime={timestamp.toISOString()}
      title={title}
      className="shrink-0 pt-2.5 text-[10px] font-medium tabular-nums tracking-[0.06em] text-slate-600 select-none font-mono"
    >
      {label}
    </time>
  )
}

function highlightKeywordClass(token: string): string {
  const normalized = token.toLowerCase()
  if (['error', 'failed', 'failure', 'blocked'].includes(normalized))
    return 'rounded px-1 py-0.5 bg-rose-500/10 text-rose-400 font-medium'
  if (['warning', 'warn', 'paused'].includes(normalized))
    return 'rounded px-1 py-0.5 bg-amber-500/10 text-amber-400 font-medium'
  if (['success', 'succeeded', 'completed', 'ok'].includes(normalized))
    return 'rounded px-1 py-0.5 bg-emerald-500/10 text-emerald-400 font-medium'
  if (['running', 'working', 'active'].includes(normalized))
    return 'rounded px-1 py-0.5 bg-sky-500/10 text-sky-400 font-medium'
  return ''
}

export function HighlightedText({
  text,
  className,
}: {
  text: string
  className?: string
}) {
  const parts = text.split(
    /(\b(?:error|failed|failure|warning|warn|success|succeeded|completed|ok|running|working|active|blocked|paused)\b)/gi,
  )
  return (
    <span className={className}>
      {parts.map((part, index) => {
        const kc = highlightKeywordClass(part)
        return kc ? (
          <span key={`${part}-${index}`} className={kc}>
            {part}
          </span>
        ) : (
          <span key={`${part}-${index}`}>{part}</span>
        )
      })}
    </span>
  )
}

export function ExpandableText({
  text,
  expandedText,
  className,
  collapsedLength = 180,
}: {
  text: string
  expandedText?: string | null
  className?: string
  collapsedLength?: number
}) {
  const [expanded, setExpanded] = useState(false)
  const collapsedText = prettifyDisplayText(text)
  const fullText = prettifyDisplayText(
    expandedText && expandedText.trim().length > 0 ? expandedText : text,
  )
  const shouldCollapse =
    fullText.length > collapsedLength || fullText !== collapsedText

  if (!shouldCollapse)
    return <HighlightedText text={fullText} className={className} />

  return (
    <div>
      <HighlightedText
        text={expanded ? fullText : shortenText(collapsedText, collapsedLength)}
        className={className}
      />
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        className="mt-1.5 inline-flex items-center rounded-md border border-slate-700/40 bg-slate-800/30 px-2.5 py-0.5 text-[10px] font-medium text-slate-500 transition-all hover:bg-slate-800/60 hover:text-slate-300 hover:border-slate-600/40"
      >
        {expanded ? 'Less' : 'More'}
      </button>
    </div>
  )
}
