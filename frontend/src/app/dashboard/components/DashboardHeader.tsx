import { LayoutDashboard } from 'lucide-react'
import { cn } from '@/lib/utils'

interface DashboardHeaderProps {
  status: { status: string } | undefined
  daysRange: number
  showRangeDropdown: boolean
  onToggleDropdown: () => void
  onRangeChange: (days: number) => void
}

const TIME_RANGE_OPTIONS = [
  { value: 1, label: '1d' },
  { value: 7, label: '7d' },
  { value: 14, label: '14d' },
  { value: 30, label: '30d' },
]

export function DashboardHeader({
  status,
  daysRange,
  onRangeChange,
}: DashboardHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-container px-4 lg:px-8">
        <div className="page-header-row">
          <div className="page-title-group">
            <div className="page-title-icon">
              <LayoutDashboard className="h-5 w-5" />
            </div>
            <div className="page-title-stack">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="page-title">Dashboard</h1>
                {status && (
                  <div
                    className={cn(
                      'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]',
                      status.status === 'healthy'
                        ? 'border-emerald-500/15 bg-emerald-500/10 text-emerald-300'
                        : 'border-amber-500/15 bg-amber-500/10 text-amber-300',
                    )}
                  >
                    <span
                      className={cn(
                        'h-1.5 w-1.5 rounded-full',
                        status.status === 'healthy'
                          ? 'bg-emerald-400'
                          : 'bg-amber-400',
                      )}
                    />
                    {status.status}
                  </div>
                )}
              </div>
              <div className="page-meta">
                <span>
                  Live command-center overview for requests, health, cost, and
                  memory.
                </span>
                <span className="page-pill">{daysRange}-day view</span>
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-800/80 bg-slate-900/80 p-1 shadow-[0_18px_40px_-30px_rgba(0,0,0,0.9)]">
            <div className="flex items-center gap-1">
              {TIME_RANGE_OPTIONS.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => onRangeChange(value)}
                  className={cn(
                    'rounded-xl px-3 py-1.5 text-xs font-semibold transition-all duration-150',
                    daysRange === value
                      ? 'bg-amber-500 text-slate-950 shadow-[0_16px_28px_-22px_rgba(245,158,11,0.9)]'
                      : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </header>
  )
}
