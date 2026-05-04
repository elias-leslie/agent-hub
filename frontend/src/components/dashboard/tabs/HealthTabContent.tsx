'use client'

import { Activity, Layers, Shield, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { DashboardStatsResponse } from '@/lib/api'
import { fetchProviderHealth, type ProviderHealth } from '@/lib/api/dashboard'
import type { StatusResponse } from '@/lib/api/status'
import { formatLatency, formatNumber } from '@/lib/formatters'
import { cn } from '@/lib/utils'

// ─────────────────────────────────────────────────────────────────────────────
// SYSTEM HEALTH TAB CONTENT
// ─────────────────────────────────────────────────────────────────────────────

function stateColor(state: string) {
  if (state === 'healthy') return 'bg-emerald-500/10 text-emerald-400'
  if (state === 'degraded') return 'bg-amber-500/10 text-amber-400'
  if (state === 'down') return 'bg-red-500/10 text-red-400 animate-pulse'
  return 'bg-slate-500/10 text-slate-400'
}

function ProviderHealthPanel() {
  const [providers, setProviders] = useState<ProviderHealth[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const res = await fetchProviderHealth()
        if (mounted) {
          setProviders(res.providers)
          setError(false)
        }
      } catch {
        if (mounted) setError(true)
      } finally {
        if (mounted) setLoading(false)
      }
    }
    load()
    const interval = setInterval(load, 30_000)
    return () => {
      mounted = false
      clearInterval(interval)
    }
  }, [])

  if (loading)
    return <div className="h-24 bg-slate-800 rounded animate-pulse" />
  if (error)
    return (
      <div className="flex items-center justify-center h-20 text-red-400/70 text-xs">
        Failed to load provider health
      </div>
    )
  if (providers.length === 0)
    return (
      <div className="flex items-center justify-center h-20 text-slate-500 text-xs">
        No provider data available
      </div>
    )

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {providers.map((p) => (
        <div
          key={p.provider}
          className="p-3 rounded-lg bg-slate-900/50 border border-slate-800"
        >
          <div className="flex items-center justify-between mb-2">
            <p className="text-[11px] font-semibold text-slate-300 capitalize">
              {p.provider}
            </p>
            <span
              className={cn(
                'px-1.5 py-0.5 rounded-full text-[8px] font-bold uppercase',
                stateColor(p.state),
              )}
            >
              {p.state}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2 text-center">
            <div>
              <p className="text-xs font-mono font-bold text-slate-200">
                {formatLatency(p.latency_ms)}
              </p>
              <p className="text-[8px] text-slate-500 uppercase">Latency</p>
            </div>
            <div>
              <p className="text-xs font-mono font-bold text-slate-200">
                {p.availability.toFixed(1)}%
              </p>
              <p className="text-[8px] text-slate-500 uppercase">Avail</p>
            </div>
          </div>
          {p.last_error && (
            <p
              className="text-[9px] text-red-400/70 mt-2 truncate"
              title={p.last_error}
            >
              {p.last_error}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}

export function HealthTabContent({
  stats,
  status,
}: {
  stats: DashboardStatsResponse | undefined
  status: StatusResponse | undefined
}) {
  if (!stats) return <div className="h-48 bg-slate-800 rounded animate-pulse" />

  return (
    <div className="space-y-4">
      {/* Provider Health */}
      <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
          <Shield className="h-3 w-3" />
          Provider Health
        </h4>
        <ProviderHealthPanel />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Memory System */}
        <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50">
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
            <Layers className="h-3 w-3" />
            Memory System
          </h4>
          <div className="space-y-3">
            <div>
              <div className="flex justify-between text-[11px] mb-1">
                <span className="text-slate-400">Success Rate</span>
                <span className="text-slate-100 font-mono">
                  {stats.memory.total_injections > 0
                    ? `${(stats.requests.success_rate * 100).toFixed(1)}%`
                    : '0%'}
                </span>
              </div>
              <div className="h-1 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500"
                  style={{ width: `${stats.requests.success_rate * 100}%` }}
                />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2 mt-2">
              <div className="p-2 rounded bg-slate-900/50 border border-slate-800">
                <p className="text-[9px] text-slate-500 uppercase">Mandates</p>
                <p className="text-xs font-mono font-bold text-slate-200">
                  {formatNumber(stats.memory.total_mandates)}
                </p>
              </div>
              <div className="p-2 rounded bg-slate-900/50 border border-slate-800">
                <p className="text-[9px] text-slate-500 uppercase">
                  Guardrails
                </p>
                <p className="text-xs font-mono font-bold text-slate-200">
                  {formatNumber(stats.memory.total_guardrails)}
                </p>
              </div>
              <div className="p-2 rounded bg-slate-900/50 border border-slate-800">
                <p className="text-[9px] text-slate-500 uppercase">
                  References
                </p>
                <p className="text-xs font-mono font-bold text-slate-200">
                  {formatNumber(stats.memory.total_references)}
                </p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 mt-2">
              <div className="p-2 rounded bg-slate-900/50 border border-slate-800">
                <p className="text-[9px] text-slate-500 uppercase">
                  Avg Tokens
                </p>
                <p className="text-xs font-mono font-bold text-slate-200">
                  {formatNumber(stats.memory.avg_tokens)}
                </p>
              </div>
              <div className="p-2 rounded bg-slate-900/50 border border-slate-800">
                <p className="text-[9px] text-slate-500 uppercase">Latency</p>
                <p className="text-xs font-mono font-bold text-slate-200">
                  {formatLatency(stats.memory.avg_latency_ms)}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Truncations */}
        <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50">
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
            <Zap className="h-3 w-3" />
            Truncations
          </h4>
          <div className="flex flex-col justify-center h-[calc(100%-1.5rem)]">
            <div className="text-center">
              <p className="text-3xl font-mono font-bold text-slate-100">
                {stats.truncations.truncation_rate.toFixed(1)}%
              </p>
              <p className="text-[10px] text-slate-500 uppercase mt-1">
                Truncation Rate
              </p>
            </div>
            <div className="mt-4 pt-4 border-t border-slate-800 flex justify-between">
              <div className="text-center flex-1">
                <p className="text-xs font-mono font-bold text-slate-200">
                  {stats.truncations.total_truncations}
                </p>
                <p className="text-[8px] text-slate-500 uppercase">Events</p>
              </div>
              <div className="text-center flex-1 border-l border-slate-800">
                <p className="text-xs font-mono font-bold text-slate-200">
                  {stats.truncations.avg_output_tokens.toFixed(0)}
                </p>
                <p className="text-[8px] text-slate-500 uppercase">
                  Avg Tokens
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Circuit Breakers */}
        <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50 col-span-1 md:col-span-2">
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
            <Activity className="h-3 w-3" />
            Circuit Breakers
          </h4>
          <div className="grid grid-cols-2 gap-4">
            {status?.circuit_breakers ? (
              Object.entries(status.circuit_breakers).map(([name, info]) => (
                <div
                  key={name}
                  className="flex items-center justify-between p-2 rounded bg-slate-900/50 border border-slate-800"
                >
                  <div>
                    <p className="text-[10px] font-medium text-slate-300 capitalize">
                      {name}
                    </p>
                    <p className="text-[9px] text-slate-500">
                      Failures: {info.consecutive_failures}
                    </p>
                  </div>
                  <div
                    className={cn(
                      'px-2 py-0.5 rounded-full text-[9px] font-bold uppercase',
                      info.state === 'closed'
                        ? 'bg-emerald-500/10 text-emerald-400'
                        : info.state === 'open'
                          ? 'bg-red-500/10 text-red-400 animate-pulse'
                          : 'bg-amber-500/10 text-amber-400',
                    )}
                  >
                    {info.state}
                  </div>
                </div>
              ))
            ) : (
              <div className="col-span-2 flex items-center justify-center h-20 text-slate-500 text-xs">
                All systems nominal
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
