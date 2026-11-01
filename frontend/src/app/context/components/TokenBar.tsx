import { cn } from '@/lib/utils'
import { PART_COLOR, tok } from '../format'

interface Props {
  total: number | null
  harness: number | null
  ours: number | null
  brief: number | null
  /** Largest total on the page; bars are drawn on one scale so rows compare by eye. */
  scale: number
  className?: string
}

/** Stacked bar: harness | ours | brief. What the split does not explain stays hatched, so unknown never reads as zero. */
export function TokenBar({
  total,
  harness,
  ours,
  brief,
  scale,
  className,
}: Props) {
  if (total == null || scale <= 0) {
    return (
      <div
        className={cn('h-2 rounded-sm bg-slate-800/60', className)}
        role="img"
        aria-label="Not measured"
      />
    )
  }
  const known = (harness ?? 0) + (ours ?? 0) + (brief ?? 0)
  const unsplit = Math.max(0, total - known)
  const pct = (v: number) => `${(v / scale) * 100}%`
  const label = `Total ${tok(total)}: harness ${tok(harness)}, ours ${tok(ours)}, brief ${tok(brief)}${unsplit > 0 && known > 0 ? `, not split ${tok(unsplit)}` : ''}`
  return (
    <div
      className={cn(
        'flex h-2 w-full overflow-hidden rounded-sm bg-slate-800/40',
        className,
      )}
      role="img"
      aria-label={label}
      title={label}
    >
      {harness != null && harness > 0 && (
        <span style={{ width: pct(harness), background: PART_COLOR.harness }} />
      )}
      {ours != null && ours > 0 && (
        <span style={{ width: pct(ours), background: PART_COLOR.ours }} />
      )}
      {brief != null && brief > 0 && (
        <span style={{ width: pct(brief), background: PART_COLOR.brief }} />
      )}
      {unsplit > 0 && (
        <span
          style={{
            width: pct(unsplit),
            background:
              'repeating-linear-gradient(135deg, #475569 0 2px, #1e293b 2px 4px)',
          }}
        />
      )}
    </div>
  )
}

export function PartsLegend({ className }: { className?: string }) {
  const items: Array<[string, string, string]> = [
    [
      'Harness',
      PART_COLOR.harness,
      "the harness's own prompt, tools and listings",
    ],
    [
      'Ours',
      PART_COLOR.ours,
      'what Agent Hub delivers: memories, prompts, project notes',
    ],
    ['Brief', PART_COLOR.brief, 'the first user message'],
  ]
  return (
    <div
      className={cn(
        'flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400',
        className,
      )}
    >
      {items.map(([name, color, hint]) => (
        <span
          key={name}
          className="inline-flex items-center gap-1.5"
          title={hint}
        >
          <span className="h-2 w-2 rounded-sm" style={{ background: color }} />
          {name}
        </span>
      ))}
      <span
        className="inline-flex items-center gap-1.5"
        title="Part of the total the split could not place"
      >
        <span
          className="h-2 w-2 rounded-sm"
          style={{
            background:
              'repeating-linear-gradient(135deg, #475569 0 2px, #1e293b 2px 4px)',
          }}
        />
        Not split
      </span>
    </div>
  )
}
