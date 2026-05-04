'use client'

import { clsx } from 'clsx'
import { CalendarClock, Loader2 } from 'lucide-react'
import type { WorkflowSchedule } from '@/lib/api'

interface WorkflowSchedulesSectionProps {
  schedules: WorkflowSchedule[]
  updatingScheduleId: string | null
  onToggle: (schedule: WorkflowSchedule) => void
}

function categoryTone(category: string): string {
  switch (category) {
    case 'persona':
      return 'border-fuchsia-700/60 bg-fuchsia-950/20 text-fuchsia-300'
    case 'observability':
      return 'border-sky-700/60 bg-sky-950/20 text-sky-300'
    case 'memory':
      return 'border-emerald-700/60 bg-emerald-950/20 text-emerald-300'
    case 'catalog':
      return 'border-cyan-700/60 bg-cyan-950/20 text-cyan-300'
    default:
      return 'border-slate-700 bg-slate-800/70 text-slate-300'
  }
}

export function WorkflowSchedulesSection({
  schedules,
  updatingScheduleId,
  onToggle,
}: WorkflowSchedulesSectionProps) {
  return (
    <section>
      <div className="flex items-center gap-3 mb-4">
        <CalendarClock className="w-5 h-5 text-cyan-400" />
        <h2 className="text-lg font-semibold text-slate-100">
          Workflow Schedules
        </h2>
        <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
          {schedules.length} cron workflows
        </span>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {schedules.map((schedule) => {
          const isPending = updatingScheduleId === schedule.schedule_id
          return (
            <div
              key={schedule.schedule_id}
              className="rounded-xl border border-slate-800 bg-slate-900/70 p-5"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-semibold text-slate-100">
                      {schedule.label}
                    </h3>
                    <span
                      className={clsx(
                        'inline-flex rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em]',
                        categoryTone(schedule.category),
                      )}
                    >
                      {schedule.category}
                    </span>
                    <span className="inline-flex rounded-full border border-slate-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-400">
                      {schedule.cron}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-slate-400 leading-6">
                    {schedule.description}
                  </p>
                  {schedule.notes && (
                    <p className="mt-3 rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2 text-xs text-slate-400">
                      {schedule.notes}
                    </p>
                  )}
                </div>

                <button
                  type="button"
                  onClick={() => onToggle(schedule)}
                  disabled={isPending}
                  role="switch"
                  aria-checked={schedule.enabled}
                  aria-label={
                    schedule.enabled
                      ? `Disable ${schedule.label}`
                      : `Enable ${schedule.label}`
                  }
                  className={clsx(
                    'relative h-6 w-12 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/40 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900',
                    schedule.enabled ? 'bg-cyan-500' : 'bg-slate-600',
                  )}
                >
                  <span
                    className={clsx(
                      'absolute top-1 h-4 w-4 rounded-full bg-slate-100 shadow-sm transition-transform',
                      schedule.enabled ? 'translate-x-7' : 'translate-x-1',
                    )}
                  />
                </button>
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-3 text-xs">
                <span
                  className={clsx(
                    'inline-flex rounded-full px-2 py-1 font-medium',
                    schedule.enabled
                      ? 'bg-emerald-500/10 text-emerald-300'
                      : 'bg-slate-800 text-slate-400',
                  )}
                >
                  {schedule.enabled ? 'Enabled' : 'Disabled'}
                </span>
                {schedule.updated_by && (
                  <span className="text-slate-500">
                    Updated by {schedule.updated_by}
                  </span>
                )}
                {isPending && (
                  <span className="inline-flex items-center gap-1 text-cyan-300">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Saving
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
