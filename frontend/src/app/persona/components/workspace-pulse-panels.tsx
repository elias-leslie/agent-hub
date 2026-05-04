'use client'

import { AlertCircle, ChevronDown, Sparkles } from 'lucide-react'
import { useState } from 'react'

import type { PersonaPulseSummary } from '@/lib/api/persona-stream'
import { cn } from '@/lib/utils'
import {
  type FilterMode,
  pulseTagClasses,
  pulseTagLabel,
  pulseTagToFilterMode,
  rootCauseLabel,
} from './pulse-helpers'
import { formatRuntimeLabel, rootCauseClasses } from './workspace-utils'

// ─── PulseOverviewPanels (collapsible) ───

export function PulseOverviewPanels({
  visiblePulseMetrics,
  pulse,
  applyPulseFilter,
  inspectAgentPulse,
}: {
  visiblePulseMetrics: PersonaPulseSummary['metrics']
  pulse: PersonaPulseSummary
  applyPulseFilter: (
    nextMode: FilterMode,
    nextAnchorEntryId?: string | null,
  ) => void
  inspectAgentPulse: (agentSlugValue: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const totalFriction = pulse.metrics.reduce((sum, m) => sum + m.count, 0)

  if (
    visiblePulseMetrics.length === 0 &&
    pulse.issue_groups.length === 0 &&
    pulse.agent_scorecards.length === 0
  )
    return null

  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2.5 rounded-xl px-3.5 py-2 text-xs font-medium text-slate-500 transition-all hover:bg-slate-800/30 hover:text-slate-400"
      >
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 transition-transform duration-200',
            !expanded && '-rotate-90',
          )}
        />
        <Sparkles className="h-3.5 w-3.5" />
        Health overview
        {totalFriction > 0 && (
          <span className="rounded-md bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-400/80">
            {totalFriction} events
          </span>
        )}
      </button>

      {expanded && (
        <div className="mt-2 space-y-3 rounded-xl border border-slate-800/40 bg-slate-900/30 p-4">
          {visiblePulseMetrics.length > 0 && (
            <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-4">
              {visiblePulseMetrics.map((metric) => {
                const mode = pulseTagToFilterMode(metric.key)
                return (
                  <button
                    key={metric.key}
                    type="button"
                    onClick={() => applyPulseFilter(mode)}
                    className={cn(
                      'rounded-xl border px-3.5 py-2.5 text-left transition-all',
                      metric.count > 0
                        ? 'border-slate-700/40 bg-slate-800/30 hover:border-slate-600/50 hover:bg-slate-800/40'
                        : 'border-slate-800/30 bg-slate-900/20',
                    )}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span
                        className={cn(
                          'rounded-md px-2 py-0.5 text-[10px] font-medium',
                          pulseTagClasses(metric.key),
                        )}
                      >
                        {metric.label}
                      </span>
                      <span className="text-base font-semibold text-slate-200 tabular-nums">
                        {metric.count}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      {metric.description}
                    </p>
                  </button>
                )
              })}
            </div>
          )}

          {(pulse.issue_groups.length > 0 ||
            pulse.agent_scorecards.length > 0) && (
            <div className="grid gap-3 xl:grid-cols-[1.3fr_1fr]">
              <section>
                <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 mb-2">
                  <AlertCircle className="h-3 w-3" />
                  Repeated Friction
                </div>
                {pulse.issue_groups.length === 0 ? (
                  <p className="text-xs text-slate-500">No repeated issues.</p>
                ) : (
                  <div className="space-y-2">
                    {pulse.issue_groups.map((issue) => (
                      <button
                        key={issue.fingerprint}
                        type="button"
                        onClick={() =>
                          applyPulseFilter(
                            pulseTagToFilterMode(issue.primary_tag),
                            issue.latest_entry_id,
                          )
                        }
                        className="w-full rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2 text-left transition hover:border-slate-700"
                      >
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span
                            className={cn(
                              'rounded-full px-2 py-0.5 text-[10px] font-medium',
                              pulseTagClasses(issue.primary_tag),
                            )}
                          >
                            {pulseTagLabel(issue.primary_tag)}
                          </span>
                          <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">
                            {issue.count}x
                          </span>
                          {issue.root_cause && (
                            <span
                              className={cn(
                                'rounded-full px-2 py-0.5 text-[10px]',
                                rootCauseClasses(issue.root_cause),
                              )}
                            >
                              {rootCauseLabel(issue.root_cause)}
                            </span>
                          )}
                        </div>
                        <div className="mt-1 text-xs font-medium text-slate-200">
                          {issue.title}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </section>
              <section>
                <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 mb-2">
                  <Sparkles className="h-3 w-3" />
                  Agent Scorecards
                </div>
                {pulse.agent_scorecards.length === 0 ? (
                  <p className="text-xs text-slate-500">
                    No agent sessions yet.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {pulse.agent_scorecards.map((sc) => {
                      const successRate =
                        sc.session_count > 0
                          ? Math.round(
                              (sc.success_count / sc.session_count) * 100,
                            )
                          : 0
                      const runtimeLbl = formatRuntimeLabel(
                        sc.median_runtime_seconds,
                      )
                      return (
                        <button
                          key={sc.agent_slug}
                          type="button"
                          onClick={() => inspectAgentPulse(sc.agent_slug)}
                          className="w-full rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2 text-left transition hover:border-slate-700"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-medium text-slate-200">
                              {sc.label}
                            </span>
                            <span className="text-[10px] text-slate-500">
                              {successRate}% / {sc.session_count} runs
                            </span>
                          </div>
                          {(sc.friction_count > 0 ||
                            sc.error_count > 0 ||
                            runtimeLbl) && (
                            <div className="mt-1 flex flex-wrap gap-1.5 text-[10px] text-slate-500">
                              {sc.friction_count > 0 && (
                                <span
                                  className={cn(
                                    'rounded-full px-1.5 py-0.5',
                                    pulseTagClasses('friction'),
                                  )}
                                >
                                  {sc.friction_count} friction
                                </span>
                              )}
                              {sc.error_count > 0 && (
                                <span className="rounded-full bg-rose-950/40 px-1.5 py-0.5 text-rose-300">
                                  {sc.error_count} errors
                                </span>
                              )}
                              {runtimeLbl && (
                                <span className="rounded-full bg-slate-800 px-1.5 py-0.5 text-slate-400">
                                  {runtimeLbl}
                                </span>
                              )}
                            </div>
                          )}
                        </button>
                      )
                    })}
                  </div>
                )}
              </section>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
