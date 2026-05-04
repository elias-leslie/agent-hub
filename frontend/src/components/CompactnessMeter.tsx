'use client'

import { AlertTriangle, CheckCircle2, Minimize2 } from 'lucide-react'

import { analyzeCompactness, type CompactnessKind } from '@/lib/compactness'
import { cn } from '@/lib/utils'

interface CompactnessMeterProps {
  content: string
  kind: CompactnessKind
  className?: string
}

export function CompactnessMeter({
  content,
  kind,
  className,
}: CompactnessMeterProps) {
  const report = analyzeCompactness(content, kind)
  const blocked = report.errors.length > 0
  const healthy = !blocked && report.warnings.length === 0

  return (
    <div
      className={cn(
        'rounded-lg border px-3 py-3',
        blocked
          ? 'border-rose-900/80 bg-rose-950/20'
          : healthy
            ? 'border-emerald-900/80 bg-emerald-950/20'
            : 'border-amber-900/80 bg-amber-950/20',
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-slate-300">
            <Minimize2 className="h-3.5 w-3.5" />
            Compactness
          </div>
          <p
            className={cn(
              'mt-1 text-sm',
              blocked
                ? 'text-rose-100'
                : healthy
                  ? 'text-emerald-100'
                  : 'text-amber-100',
            )}
          >
            {blocked
              ? kind === 'prompt'
                ? 'Write strict Caveman. Save should fail until prose is tightened.'
                : 'Write one strict Caveman rule. Save should fail until tightened.'
              : healthy
                ? kind === 'prompt'
                  ? 'Lean enough for routine edits.'
                  : 'Lean enough for one reusable rule.'
                : kind === 'prompt'
                  ? 'Trim filler before this prompt grows further.'
                  : 'Trim or split this memory before it drifts.'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded-md border border-slate-700 bg-slate-950/70 px-2 py-1 text-slate-200">
            ~{report.tokens} tok
          </span>
          <span className="rounded-md border border-slate-700 bg-slate-950/70 px-2 py-1 text-slate-200">
            {report.lines}L
          </span>
          <span className="rounded-md border border-slate-700 bg-slate-950/70 px-2 py-1 text-slate-200">
            {report.chars}c
          </span>
        </div>
      </div>
      <div
        className={cn(
          'mt-3 flex items-start gap-2 text-xs',
          blocked
            ? 'text-rose-200'
            : healthy
              ? 'text-emerald-200'
              : 'text-amber-200',
        )}
      >
        {healthy ? (
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        ) : (
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        )}
        <div className="space-y-1">
          {healthy ? (
            <p>
              {kind === 'prompt'
                ? 'Keep signal, cut overlap, avoid repeated examples.'
                : 'Keep one atomic rule and avoid conversational phrasing.'}
            </p>
          ) : (
            [...report.errors, ...report.warnings].map((message) => (
              <p key={message}>{message}</p>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
