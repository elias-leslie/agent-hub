'use client'

import { Layers, Shield } from 'lucide-react'
import { useEffect, useState } from 'react'
import { getProviderInfo } from '@/components/settings/constants'
import type { DashboardStatsResponse } from '@/lib/api'
import { fetchProviderHealth, type ProviderHealth } from '@/lib/api/dashboard'
import { formatLatency, formatNumber } from '@/lib/formatters'
import { cn } from '@/lib/utils'

// ─────────────────────────────────────────────────────────────────────────────
// SYSTEM HEALTH TAB CONTENT
// ─────────────────────────────────────────────────────────────────────────────

function stateColor(state: string) {
  if (state === 'healthy' || state === 'ready')
    return 'bg-emerald-500/10 text-emerald-400'
  if (state === 'degraded') return 'bg-amber-500/10 text-amber-400'
  if (state === 'down' || state === 'unavailable')
    return 'bg-red-500/10 text-red-400 animate-pulse'
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
            <p className="text-[11px] font-semibold text-slate-300">
              {getProviderInfo(p.provider).name}
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
          <div className="grid grid-cols-3 gap-2 text-center">
            <div>
              <p className="text-xs font-mono font-bold text-slate-200">
                {formatNumber(p.recent_calls)}
              </p>
              <p className="text-[8px] text-slate-500 uppercase">Calls 24h</p>
            </div>
            <div>
              <p
                className={cn(
                  'text-xs font-mono font-bold',
                  p.recent_failures > 0 ? 'text-amber-400' : 'text-slate-200',
                )}
              >
                {formatNumber(p.recent_failures)}
              </p>
              <p className="text-[8px] text-slate-500 uppercase">Failed</p>
            </div>
            <div>
              <p className="text-xs font-mono font-bold text-slate-200">
                {p.latency_ms == null ? '-' : formatLatency(p.latency_ms)}
              </p>
              <p className="text-[8px] text-slate-500 uppercase">Latency</p>
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

function MemoryCount({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-2 rounded bg-slate-900/50 border border-slate-800">
      <p className="text-[9px] text-slate-500 uppercase">{label}</p>
      <p className="text-xs font-mono font-bold text-slate-200">{value}</p>
    </div>
  )
}

export function HealthTabContent({
  stats,
}: {
  stats: DashboardStatsResponse | undefined
}) {
  if (!stats) return <div className="h-48 bg-slate-800 rounded animate-pulse" />

  const memory = stats.memory

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

      {/* Memory injection: selected references and passive reference-index
          entries are separate counts by policy. */}
      <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
          <Layers className="h-3 w-3" />
          Memory Injection
        </h4>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
          <MemoryCount
            label="Injections"
            value={formatNumber(memory.total_injections)}
          />
          <MemoryCount
            label="Selected refs"
            value={formatNumber(memory.total_references)}
          />
          <MemoryCount
            label="Passive index refs"
            value={formatNumber(memory.total_reference_index_entries)}
          />
          <MemoryCount
            label="Cited refs"
            value={formatNumber(memory.total_reference_citations)}
          />
          <MemoryCount
            label="Mandates"
            value={formatNumber(memory.total_mandates)}
          />
          <MemoryCount
            label="Guardrails"
            value={formatNumber(memory.total_guardrails)}
          />
          <MemoryCount
            label="Avg tokens"
            value={formatNumber(Math.round(memory.avg_tokens))}
          />
          <MemoryCount
            label="Avg latency"
            value={formatLatency(memory.avg_latency_ms)}
          />
        </div>
      </div>
    </div>
  )
}
