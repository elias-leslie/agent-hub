'use client'

import { Layers } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'
import { CONTEXT_DAYS, type ContextDays } from '@/lib/api/context-observability'
import { cn } from '@/lib/utils'

const TABS = [
  { href: '/context', label: 'Cost' },
  { href: '/context/trend', label: 'Trend' },
  { href: '/context/changes', label: 'Changes' },
] as const

function tabActive(pathname: string, href: string) {
  if (href === '/context') {
    return pathname === '/context' || pathname.startsWith('/context/cell')
  }
  return pathname === href || pathname.startsWith(`${href}/`)
}

export function RangeToggle({
  days,
  onChange,
}: {
  days: ContextDays
  onChange: (days: ContextDays) => void
}) {
  return (
    <div
      className="rounded-2xl border border-slate-800/80 bg-slate-900/80 p-1"
      role="group"
      aria-label="Time range"
    >
      <div className="flex items-center gap-1">
        {CONTEXT_DAYS.map((d) => (
          <button
            key={d}
            type="button"
            aria-pressed={days === d}
            onClick={() => onChange(d)}
            className={cn(
              'rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors focus-ring-amber',
              days === d
                ? 'bg-amber-500 text-slate-950'
                : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100',
            )}
          >
            {d}d
          </button>
        ))}
      </div>
    </div>
  )
}

/** Title, the Cost | Trend | Changes tabs and a slot for the page's own controls. */
export function ContextHeader({
  title = 'Context',
  controls,
}: {
  title?: string
  controls?: ReactNode
}) {
  const pathname = usePathname()
  return (
    <header className="page-header max-sm:static">
      <div className="page-container px-4 lg:px-8">
        <div className="page-header-row">
          <div className="page-title-group">
            <div className="page-title-icon">
              <Layers className="h-5 w-5" />
            </div>
            <div className="page-title-stack">
              <h1 className="page-title">{title}</h1>
            </div>
            <nav aria-label="Context sections" className="flex gap-1">
              {TABS.map((tab) => {
                const active = tabActive(pathname, tab.href)
                return (
                  <Link
                    key={tab.href}
                    href={tab.href}
                    prefetch={false}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors focus-ring-amber',
                      active
                        ? 'bg-slate-800 text-amber-200'
                        : 'text-slate-400 hover:bg-slate-800/70 hover:text-slate-100',
                    )}
                  >
                    {tab.label}
                  </Link>
                )
              })}
            </nav>
          </div>
          {controls && (
            <div className="flex flex-wrap items-center gap-2">{controls}</div>
          )}
        </div>
      </div>
    </header>
  )
}
