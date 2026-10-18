'use client'

import { Sparkline } from '@/components/dashboard/Sparkline'
import type { SpendItem } from '@/lib/api/analytics'
import { cn } from '@/lib/utils'
import { KIND_META, share, tokens, usd } from '../format'

function KindTag({ kind }: { kind: SpendItem['kind'] }) {
  const meta = KIND_META[kind] ?? KIND_META.other
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-slate-400"
      title={meta.hint}
    >
      <span className={cn('h-2 w-2 rounded-full', meta.dot)} />
      {meta.label}
    </span>
  )
}

function ShareBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full bg-amber-400/80"
          style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }}
        />
      </div>
      <span className="w-9 text-right font-mono text-xs text-slate-400">
        {share(value)}
      </span>
    </div>
  )
}

export function CostTable({
  items,
  selected,
  onOpen,
}: {
  items: SpendItem[]
  selected: string | null
  onOpen: (key: string) => void
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-left text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            <th className="py-2 pr-3 font-semibold">Name</th>
            <th className="hidden w-28 py-2 pr-3 font-semibold md:table-cell">
              Kind
            </th>
            <th className="hidden w-32 py-2 pr-3 font-semibold lg:table-cell">
              Project
            </th>
            <th className="w-20 py-2 pr-3 text-right font-semibold">Cost</th>
            <th className="hidden w-32 py-2 pr-3 font-semibold sm:table-cell">
              Share
            </th>
            <th className="hidden w-20 py-2 pr-3 text-right font-semibold md:table-cell">
              Tokens
            </th>
            <th className="hidden w-24 py-2 font-semibold lg:table-cell">
              Trend
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.key}
              onClick={() => onOpen(item.key)}
              className={cn(
                'cursor-pointer border-b border-slate-800/60 transition-colors hover:bg-slate-800/40',
                selected === item.key && 'bg-slate-800/60',
              )}
            >
              <td className="py-2.5 pr-3">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    onOpen(item.key)
                  }}
                  className="block w-full truncate rounded text-left text-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400"
                  title={item.name}
                >
                  {item.name}
                </button>
                <span className="mt-0.5 flex gap-2 md:hidden">
                  <KindTag kind={item.kind} />
                  <span className="truncate text-xs text-slate-500">
                    {item.project}
                  </span>
                </span>
              </td>
              <td className="hidden py-2.5 pr-3 md:table-cell">
                <KindTag kind={item.kind} />
              </td>
              <td className="hidden truncate py-2.5 pr-3 text-xs text-slate-400 lg:table-cell">
                {item.project}
              </td>
              <td className="py-2.5 pr-3 text-right font-mono text-slate-100">
                {usd(item.usd)}
              </td>
              <td className="hidden py-2.5 pr-3 sm:table-cell">
                <ShareBar value={item.share} />
              </td>
              <td className="hidden py-2.5 pr-3 text-right font-mono text-xs text-slate-400 md:table-cell">
                {tokens(item.tokens)}
              </td>
              <td className="hidden py-2.5 lg:table-cell">
                <Sparkline
                  data={item.spark}
                  color="amber"
                  width={88}
                  height={22}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
