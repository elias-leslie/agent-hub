'use client'

import { AlertTriangle, Ghost, Repeat2, Wallet } from 'lucide-react'
import type { SessionHotspots } from '@/lib/api'

interface SessionHotspotsPanelProps {
  hotspots: SessionHotspots | null
  isLoading: boolean
}

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  return String(value)
}

function formatCost(value: number): string {
  return `$${value.toFixed(2)}`
}

function formatQuiet(seconds: number): string {
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`
  if (seconds >= 60) return `${Math.round(seconds / 60)}m`
  return `${seconds}s`
}

function EmptyState({ label }: { label: string }) {
  return <p className="text-sm text-slate-500">{label}</p>
}

export function SessionHotspotsPanel({
  hotspots,
  isLoading,
}: SessionHotspotsPanelProps) {
  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <AlertTriangle className="w-5 h-5 text-amber-400" />
        <h2 className="text-lg font-semibold text-slate-100">Churn Hotspots</h2>
        {hotspots && (
          <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
            last {hotspots.window_hours}h
          </span>
        )}
      </div>

      {isLoading || !hotspots ? (
        <div className="grid gap-4 lg:grid-cols-4">
          {[...Array(4)].map((_, index) => (
            <div
              key={index}
              className="h-28 animate-pulse rounded-xl bg-slate-800/50"
            />
          ))}
        </div>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5">
              <div className="flex items-center gap-2 text-slate-400">
                <Wallet className="h-4 w-4 text-emerald-400" />
                <span className="text-sm">Window Cost</span>
              </div>
              <div className="mt-3 text-3xl font-bold text-slate-100">
                {formatCost(hotspots.totals.total_cost_usd)}
              </div>
              <p className="mt-2 text-xs text-slate-500">
                {formatTokens(hotspots.totals.input_tokens)} in /{' '}
                {formatTokens(hotspots.totals.output_tokens)} out
              </p>
            </div>

            <div className="rounded-xl border border-amber-800/50 bg-amber-950/20 p-5">
              <div className="flex items-center gap-2 text-amber-300">
                <Repeat2 className="h-4 w-4" />
                <span className="text-sm">Rate-Limit Fallbacks</span>
              </div>
              <div className="mt-3 text-3xl font-bold text-amber-300">
                {hotspots.totals.rate_limit_fallback_sessions}
              </div>
              <p className="mt-2 text-xs text-amber-200/70">
                Sessions that burned time on 429 or rate-limit fallback paths
              </p>
            </div>

            <div className="rounded-xl border border-rose-800/50 bg-rose-950/20 p-5">
              <div className="flex items-center gap-2 text-rose-300">
                <Ghost className="h-4 w-4" />
                <span className="text-sm">Zero-Event Active</span>
              </div>
              <div className="mt-3 text-3xl font-bold text-rose-300">
                {hotspots.totals.zero_event_active_sessions}
              </div>
              <p className="mt-2 text-xs text-rose-200/70">
                Active sessions with no event trail
              </p>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5">
              <div className="flex items-center gap-2 text-slate-400">
                <AlertTriangle className="h-4 w-4 text-cyan-400" />
                <span className="text-sm">Missing Attribution</span>
              </div>
              <div className="mt-3 text-3xl font-bold text-slate-100">
                {hotspots.totals.missing_attribution_sessions}
              </div>
              <p className="mt-2 text-xs text-slate-500">
                Sessions with no request source or logical client
              </p>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5">
              <h3 className="text-sm font-semibold text-slate-100">
                Attribution Breakdown
              </h3>
              <div className="mt-4 space-y-3">
                {hotspots.attribution_breakdown.length === 0 ? (
                  <EmptyState label="No recent session data." />
                ) : (
                  hotspots.attribution_breakdown.map((row) => (
                    <div
                      key={row.kind}
                      className="rounded-lg border border-slate-800 bg-slate-950/70 px-4 py-3"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-slate-100">
                            {row.label}
                          </p>
                          <p className="text-xs text-slate-500">
                            {row.sessions} sessions ·{' '}
                            {formatTokens(row.input_tokens)} in
                          </p>
                        </div>
                        <span className="text-sm font-semibold text-slate-200">
                          {formatCost(row.total_cost_usd)}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5">
              <h3 className="text-sm font-semibold text-slate-100">
                Repeated Workloads
              </h3>
              <div className="mt-4 space-y-3">
                {hotspots.repeated_workloads.length === 0 ? (
                  <EmptyState label="No repeated workloads in the current window." />
                ) : (
                  hotspots.repeated_workloads.map((row) => (
                    <div
                      key={row.workload_key}
                      className="rounded-lg border border-slate-800 bg-slate-950/70 px-4 py-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-slate-100 truncate">
                            {row.label}
                          </p>
                          <p className="text-xs text-slate-500">
                            {row.project_id} · {row.agent_slug || '—'} ·{' '}
                            {row.sessions} sessions
                          </p>
                          {row.detail && (
                            <p className="mt-1 text-[11px] text-slate-600">
                              {row.detail}
                            </p>
                          )}
                        </div>
                        <span className="text-sm font-semibold text-amber-300">
                          {formatCost(row.total_cost_usd)}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5">
              <h3 className="text-sm font-semibold text-slate-100">
                Low-Yield Sessions
              </h3>
              <div className="mt-4 space-y-3">
                {hotspots.low_yield_sessions.length === 0 ? (
                  <EmptyState label="No high-input low-output sessions in the current window." />
                ) : (
                  hotspots.low_yield_sessions.map((row) => (
                    <div
                      key={row.session_id}
                      className="rounded-lg border border-slate-800 bg-slate-950/70 px-4 py-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-slate-100 truncate">
                            {row.label}
                          </p>
                          <p className="text-xs text-slate-500">
                            {row.project_id} · {row.agent_slug || '—'} ·{' '}
                            {row.attribution_label || 'Unknown'}
                          </p>
                          <p className="mt-1 text-[11px] text-slate-600">
                            {formatTokens(row.input_tokens)} in /{' '}
                            {formatTokens(row.output_tokens)} out · ratio{' '}
                            {row.efficiency_ratio}x
                          </p>
                        </div>
                        <span className="text-sm font-semibold text-rose-300">
                          {formatCost(row.total_cost_usd)}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5">
              <h3 className="text-sm font-semibold text-slate-100">
                Zero-Event Active Sessions
              </h3>
              <div className="mt-4 space-y-3">
                {hotspots.zero_event_active_sessions.length === 0 ? (
                  <EmptyState label="No active ghost sessions right now." />
                ) : (
                  hotspots.zero_event_active_sessions.map((row) => (
                    <div
                      key={row.session_id}
                      className="rounded-lg border border-slate-800 bg-slate-950/70 px-4 py-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-slate-100">
                            {row.project_id} · {row.agent_slug || '—'}
                          </p>
                          <p className="text-xs text-slate-500">
                            {row.request_source || 'no request source'} ·{' '}
                            {row.lifecycle_state || 'unknown'}
                          </p>
                        </div>
                        <span className="text-sm font-semibold text-rose-300">
                          quiet {formatQuiet(row.quiet_for_seconds)}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </section>
  )
}
