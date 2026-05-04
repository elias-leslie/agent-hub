import { ArrowLeft, FlaskConical, RefreshCw } from 'lucide-react'
import { useRouter } from 'next/navigation'

import { cn } from '@/lib/utils'

export type ArenaWindow = 7 | 30 | 90
export type ArenaView = 'overview' | 'suites' | 'runtime' | 'experiments'

interface ArenaHeaderProps {
  agentName: string
  slug: string
  backHref?: string
  windowDays: ArenaWindow
  activeView: ArenaView
  onWindowDaysChange: (value: ArenaWindow) => void
  onViewChange: (value: ArenaView) => void
  onRefresh: () => void
  isRefreshing: boolean
}

const VIEW_OPTIONS: Array<{ id: ArenaView; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'suites', label: 'Suites' },
  { id: 'runtime', label: 'Runtime' },
  { id: 'experiments', label: 'Experiments' },
]

export function ArenaHeader({
  agentName,
  slug,
  backHref,
  windowDays,
  activeView,
  onWindowDaysChange,
  onViewChange,
  onRefresh,
  isRefreshing,
}: ArenaHeaderProps) {
  const router = useRouter()

  return (
    <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur-sm">
      <div className="px-6 lg:px-8">
        <div className="flex flex-col gap-3 py-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-4">
              <button
                onClick={() => router.push(backHref || `/agents/${slug}`)}
                className="rounded-lg p-1.5 transition-colors hover:bg-slate-800"
                aria-label="Back"
              >
                <ArrowLeft className="h-5 w-5 text-slate-400" />
              </button>
              <div className="flex items-center gap-2">
                <FlaskConical className="h-5 w-5 text-amber-500" />
                <h1 className="text-lg font-bold tracking-tight text-slate-100">
                  {agentName}
                </h1>
                <span className="rounded bg-amber-950/40 px-2 py-0.5 text-xs font-semibold text-amber-200 ring-1 ring-amber-900">
                  Arena
                </span>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 lg:justify-end">
              <div className="flex items-center rounded-lg border border-slate-700 bg-slate-800 p-0.5">
                {([7, 30, 90] as ArenaWindow[]).map((days) => (
                  <button
                    key={days}
                    type="button"
                    onClick={() => onWindowDaysChange(days)}
                    className={cn(
                      'px-3 py-1 text-xs font-medium rounded-md transition-all duration-150',
                      windowDays === days
                        ? 'bg-amber-500 text-slate-950 shadow-sm'
                        : 'text-slate-400 hover:text-slate-200',
                    )}
                  >
                    {days}d
                  </button>
                ))}
              </div>
              <button
                onClick={onRefresh}
                disabled={isRefreshing}
                className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700 disabled:opacity-50"
              >
                <RefreshCw
                  className={cn('h-3.5 w-3.5', isRefreshing && 'animate-spin')}
                />
                Refresh
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1 rounded-lg bg-slate-800/50 p-1">
            {VIEW_OPTIONS.map((view) => (
              <button
                key={view.id}
                type="button"
                onClick={() => onViewChange(view.id)}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-semibold transition-all duration-200',
                  activeView === view.id
                    ? 'bg-amber-950/50 text-amber-200 shadow-sm ring-1 ring-amber-800/50'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60',
                )}
                aria-pressed={activeView === view.id}
              >
                {view.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </header>
  )
}
