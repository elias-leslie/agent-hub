'use client'

import {
  AlertCircle,
  BarChart3,
  CheckCircle2,
  Loader2,
  Pencil,
  Play,
  Scale,
  Search,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { NarrationTag } from '../hooks/useNarrationTags'

const TAG_CONFIG: Record<
  string,
  { icon: typeof Play; label: string; color: string }
> = {
  started: { icon: Play, label: 'Started', color: 'text-emerald-400' },
  found: { icon: Search, label: 'Found', color: 'text-sky-400' },
  modified: { icon: Pencil, label: 'Modified', color: 'text-amber-400' },
  tested: { icon: CheckCircle2, label: 'Tested', color: 'text-emerald-400' },
  confidence: {
    icon: BarChart3,
    label: 'Confidence',
    color: 'text-violet-400',
  },
  blocked: { icon: AlertCircle, label: 'Blocked', color: 'text-rose-400' },
  decision: { icon: Scale, label: 'Decision', color: 'text-amber-300' },
}

function ConfidenceMeter({ content }: { content: string }) {
  const match = content.match(/^(\d+)/)
  const value = match ? Math.min(parseInt(match[1], 10), 100) : null
  if (value === null) return null
  const remaining = content.replace(/^\d+\s*/, '').replace(/^[-–—:]\s*/, '')

  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 rounded-full bg-slate-800 overflow-hidden flex-shrink-0">
        <div
          className={cn(
            'h-full rounded-full transition-all',
            value >= 70
              ? 'bg-emerald-400'
              : value >= 40
                ? 'bg-amber-400'
                : 'bg-rose-400',
          )}
          style={{ width: `${value}%` }}
        />
      </div>
      <span className="text-xs text-slate-400">{value}%</span>
      {remaining && <span className="text-xs text-slate-500">{remaining}</span>}
    </div>
  )
}

export function NarrationTimeline({
  tags,
  loading,
  error,
}: {
  tags: NarrationTag[]
  loading: boolean
  error: string | null
}) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 py-2 text-xs text-slate-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading progress...
      </div>
    )
  }

  if (error) {
    return <p className="text-xs text-rose-400 py-1">{error}</p>
  }

  if (tags.length === 0) return null

  return (
    <div className="space-y-1">
      <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 mb-1.5">
        Progress
      </div>
      <div className="relative pl-4 border-l border-slate-800 space-y-1.5">
        {tags.map((tag) => {
          const config = TAG_CONFIG[tag.tag_type]
          if (!config) return null
          const Icon = config.icon

          return (
            <div key={tag.id} className="flex items-start gap-2 relative">
              <div
                className={cn(
                  'absolute -left-[calc(1rem+4.5px)] top-[3px] h-2 w-2 rounded-full border-2 border-slate-950',
                  tag.tag_type === 'blocked' ? 'bg-rose-400' : 'bg-slate-600',
                )}
              />
              <Icon
                className={cn('h-3.5 w-3.5 mt-0.5 flex-shrink-0', config.color)}
              />
              <div className="min-w-0 flex-1">
                {tag.tag_type === 'confidence' ? (
                  <ConfidenceMeter content={tag.content} />
                ) : (
                  <p className="text-xs text-slate-300 leading-relaxed">
                    {tag.content}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
