'use client'

import { useMemo, useState } from 'react'
import { cn } from '@/lib/utils'
import type { DiffLine, RowDiff } from '../diff'

const CONTEXT = 2
const LINE_LIMIT = 80

type Shown = DiffLine | { type: 'gap'; text: string }

/** Keep changed lines with a little context; fold long unchanged runs into one marker. */
export function collapse(lines: DiffLine[], context = CONTEXT): Shown[] {
  const keep = new Array<boolean>(lines.length).fill(false)
  lines.forEach((line, i) => {
    if (line.type === 'same') return
    for (
      let k = Math.max(0, i - context);
      k <= Math.min(lines.length - 1, i + context);
      k++
    )
      keep[k] = true
  })
  const out: Shown[] = []
  let skipped = 0
  lines.forEach((line, i) => {
    if (keep[i]) {
      if (skipped)
        out.push({
          type: 'gap',
          text: `${skipped} unchanged line${skipped > 1 ? 's' : ''}`,
        })
      skipped = 0
      out.push(line)
    } else skipped++
  })
  if (skipped)
    out.push({
      type: 'gap',
      text: `${skipped} unchanged line${skipped > 1 ? 's' : ''}`,
    })
  return out
}

const MARK = { add: '+', del: '−', same: ' ' } as const

export function DiffView({ diff, label }: { diff: RowDiff; label: string }) {
  const [all, setAll] = useState(false)
  const shown = useMemo(() => collapse(diff.lines), [diff.lines])
  const visible = all ? shown : shown.slice(0, LINE_LIMIT)
  return (
    <div className="mt-2 space-y-2" aria-label={`Diff of ${label}`}>
      {diff.fields.length > 0 && (
        <ul className="space-y-0.5 text-xs">
          {diff.fields.map((f) => (
            <li key={f.field} className="flex flex-wrap gap-x-2 text-slate-300">
              <span className="w-24 shrink-0 text-slate-500">{f.label}</span>
              <span className="min-w-0 break-words text-red-300/90 line-through decoration-red-400/40">
                {f.before}
              </span>
              <span aria-hidden="true" className="text-slate-600">
                →
              </span>
              <span className="min-w-0 break-words text-emerald-300">
                {f.after}
              </span>
            </li>
          ))}
        </ul>
      )}
      {shown.length === 0 ? (
        <p className="text-xs text-slate-500">
          {diff.fields.length
            ? 'The text is unchanged.'
            : 'No text changes to show.'}
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-800/80 bg-slate-950/70 font-mono text-[11.5px] leading-5">
          {visible.map((line, i) =>
            line.type === 'gap' ? (
              <div
                key={i}
                className="border-y border-slate-800/60 bg-slate-900/60 px-2 text-[10.5px] text-slate-500"
              >
                … {line.text}
              </div>
            ) : (
              <div
                key={i}
                className={cn(
                  'flex gap-2 px-2',
                  line.type === 'add' && 'bg-emerald-500/10 text-emerald-200',
                  line.type === 'del' && 'bg-red-500/10 text-red-200',
                  line.type === 'same' && 'text-slate-400',
                )}
              >
                <span
                  aria-hidden="true"
                  className="w-3 shrink-0 select-none text-slate-500"
                >
                  {MARK[line.type]}
                </span>
                <span className="min-w-0 whitespace-pre-wrap break-words">
                  <span className="sr-only">
                    {line.type === 'add'
                      ? 'Added: '
                      : line.type === 'del'
                        ? 'Removed: '
                        : ''}
                  </span>
                  {line.text || ' '}
                </span>
              </div>
            ),
          )}
        </div>
      )}
      {!all && shown.length > LINE_LIMIT && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="text-xs text-amber-300 underline underline-offset-2 focus-ring-amber"
        >
          Show all {shown.length} lines
        </button>
      )}
    </div>
  )
}
