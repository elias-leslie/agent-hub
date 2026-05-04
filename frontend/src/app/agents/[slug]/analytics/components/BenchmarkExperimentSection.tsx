import { AlertTriangle, CheckCircle2, RotateCcw } from 'lucide-react'

import type { AgentBenchmarkExperimentSummary } from '../types'
import { ChartCard } from './ChartCard'

interface BenchmarkExperimentSectionProps {
  experiments: AgentBenchmarkExperimentSummary[]
}

function decisionTone(decision: string) {
  if (decision === 'promote') {
    return {
      icon: CheckCircle2,
      className: 'bg-emerald-950/30 text-emerald-300 ring-1 ring-emerald-800',
    }
  }
  if (decision === 'rollback') {
    return {
      icon: RotateCcw,
      className: 'bg-rose-950/30 text-rose-300 ring-1 ring-rose-800',
    }
  }
  return {
    icon: AlertTriangle,
    className: 'bg-amber-950/30 text-amber-300 ring-1 ring-amber-800',
  }
}

function formatDelta(
  value: number | null,
  low: number | null,
  high: number | null,
  suffix = '',
) {
  if (value === null || low === null || high === null) {
    return 'Pending'
  }
  const signed = value > 0 ? `+${value}` : `${value}`
  return `${signed}${suffix} [${low}, ${high}]`
}

function formatMetric(value: number | null, suffix = '') {
  if (value === null) {
    return 'Pending'
  }
  return `${value}${suffix}`
}

export function BenchmarkExperimentSection({
  experiments,
}: BenchmarkExperimentSectionProps) {
  if (experiments.length === 0) {
    return null
  }

  return (
    <ChartCard title="Benchmark Experiments">
      <div className="grid gap-4 lg:grid-cols-2">
        {experiments.map((experiment) => {
          const tone = decisionTone(experiment.decision)
          const DecisionIcon = tone.icon
          return (
            <article
              key={experiment.experiment_key}
              className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-100">
                    {experiment.name}
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    {experiment.suite_id}
                  </p>
                </div>
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${tone.className}`}
                >
                  <DecisionIcon className="h-3.5 w-3.5" />
                  {experiment.decision}
                </span>
              </div>

              {experiment.hypothesis && (
                <p className="mt-3 text-sm text-slate-300">
                  {experiment.hypothesis}
                </p>
              )}

              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-lg bg-slate-950/50 p-3">
                  <p className="text-xs uppercase tracking-wide text-slate-400">
                    {experiment.baseline.label}
                  </p>
                  <p className="mt-1 font-semibold text-slate-100">
                    {experiment.baseline.run_count} runs
                  </p>
                  <p className="mt-1 text-slate-300">
                    Score {experiment.baseline.avg_score ?? 'Pending'}
                  </p>
                  <p className="text-slate-300">
                    Pass {experiment.baseline.avg_pass_rate ?? 'Pending'}%
                  </p>
                  <p className="text-slate-300">
                    Tools {formatMetric(experiment.baseline.avg_tool_calls)}
                  </p>
                </div>
                <div className="rounded-lg bg-slate-950/50 p-3">
                  <p className="text-xs uppercase tracking-wide text-slate-400">
                    {experiment.candidate.label}
                  </p>
                  <p className="mt-1 font-semibold text-slate-100">
                    {experiment.candidate.run_count} runs
                  </p>
                  <p className="mt-1 text-slate-300">
                    Score {experiment.candidate.avg_score ?? 'Pending'}
                  </p>
                  <p className="text-slate-300">
                    Pass {experiment.candidate.avg_pass_rate ?? 'Pending'}%
                  </p>
                  <p className="text-slate-300">
                    Tools {formatMetric(experiment.candidate.avg_tool_calls)}
                  </p>
                </div>
              </div>

              <dl className="mt-4 space-y-2 text-sm">
                <div className="flex items-start justify-between gap-4">
                  <dt className="text-slate-400">Score delta</dt>
                  <dd className="text-right text-slate-200">
                    {formatDelta(
                      experiment.score_delta.mean_delta,
                      experiment.score_delta.ci_low,
                      experiment.score_delta.ci_high,
                    )}
                  </dd>
                </div>
                <div className="flex items-start justify-between gap-4">
                  <dt className="text-slate-400">Pass delta</dt>
                  <dd className="text-right text-slate-200">
                    {formatDelta(
                      experiment.pass_rate_delta.mean_delta,
                      experiment.pass_rate_delta.ci_low,
                      experiment.pass_rate_delta.ci_high,
                      '%',
                    )}
                  </dd>
                </div>
                <div className="flex items-start justify-between gap-4">
                  <dt className="text-slate-400">Tool-call delta</dt>
                  <dd className="text-right text-slate-200">
                    {formatDelta(
                      experiment.tool_call_delta.mean_delta,
                      experiment.tool_call_delta.ci_low,
                      experiment.tool_call_delta.ci_high,
                    )}
                  </dd>
                </div>
                <div className="flex items-start justify-between gap-4">
                  <dt className="text-slate-400">Reason</dt>
                  <dd className="text-right text-slate-200">
                    {experiment.decision_reason ?? 'Pending'}
                  </dd>
                </div>
                <div className="flex items-start justify-between gap-4">
                  <dt className="text-slate-400">Config stability</dt>
                  <dd className="text-right text-slate-200">
                    {experiment.baseline.config_stable &&
                    experiment.candidate.config_stable
                      ? 'Frozen'
                      : 'Mixed'}
                  </dd>
                </div>
              </dl>
            </article>
          )
        })}
      </div>
    </ChartCard>
  )
}
