import { Code2 } from 'lucide-react'
import { ModelPill } from '@/app/sessions/components/ModelPill'
import { cn } from '@/lib/utils'
import type { Agent, AgentMetrics } from '../lib/types'
import { AgentActionsMenu } from './AgentActionsMenu'
import { MetricCell } from './MetricCell'

export function AgentRow({
  agent,
  metrics,
  onClone,
  onArchive,
}: {
  agent: Agent
  metrics: AgentMetrics | null
  onClone: (agent: Agent) => void
  onArchive: (agent: Agent) => void
}) {
  const requests24h = metrics?.requests_24h ?? 0
  const successLabel =
    requests24h > 0
      ? `${(metrics?.success_rate ?? 0).toFixed(1)}% ok`
      : 'no data'
  const cost24hUsd = metrics?.cost_24h_usd ?? 0

  return (
    <div
      className={cn(
        'grid grid-cols-[220px_1fr_130px_130px_110px_40px] items-center gap-3 px-5 py-4 transition-colors',
        agent.is_active ? 'hover:bg-slate-800/35' : 'hover:bg-slate-800/20',
      )}
    >
      {/* Agent Name & Slug */}
      <div className="min-w-0">
        <div className="grid min-w-0 grid-cols-[auto_1fr_auto] items-start gap-1.5">
          <span
            className={cn(
              'h-1.5 w-1.5 rounded-full shrink-0',
              agent.is_active ? 'bg-emerald-500' : 'bg-slate-400',
            )}
            title={agent.is_active ? 'Active' : 'Inactive'}
          />
          <a
            href={`/agents/${agent.slug}`}
            className={cn(
              'block min-w-0 line-clamp-2 text-sm font-semibold leading-tight transition-colors hover:text-amber-300',
              agent.is_active ? 'text-slate-100' : 'text-slate-400',
            )}
          >
            {agent.name}
          </a>
          {agent.is_coding_agent && (
            <span title="Coding specialist" className="mt-0.5">
              <Code2 className="h-3.5 w-3.5 text-cyan-400 shrink-0" />
            </span>
          )}
        </div>
        <span className="text-[10px] text-slate-400 font-mono">
          {agent.slug}
        </span>
      </div>

      {/* Model Stack */}
      <div className="flex flex-wrap gap-1 items-center">
        <ModelPill model={agent.primary_model_id} />
        <span className="rounded-full border border-slate-800/70 bg-slate-900/80 px-2 py-1 text-[10px] font-mono text-slate-400">
          v{agent.version}
        </span>
        {agent.fallback_models.length > 0 && (
          <span className="text-[10px] text-slate-400">
            +{agent.fallback_models.length} fallback
          </span>
        )}
      </div>

      {/* Requests 24h + success summary */}
      <div className="min-w-[90px]">
        <div className="text-xs font-semibold tabular-nums text-slate-300">
          {requests24h}
        </div>
        <div className="text-[10px] text-slate-400 tabular-nums">
          {successLabel}
        </div>
      </div>

      {/* Latency with sparkline */}
      <MetricCell
        label="Latency"
        value={metrics?.avg_latency_ms?.toFixed(0) ?? '—'}
        unit="ms"
        trend={metrics?.latency_trend}
        color="amber"
      />

      {/* Cost 24h */}
      <div className="text-right">
        <span className="text-xs font-semibold tabular-nums text-slate-300">
          ${cost24hUsd.toFixed(2)}
        </span>
      </div>

      {/* Actions */}
      <AgentActionsMenu agent={agent} onClone={onClone} onArchive={onArchive} />
    </div>
  )
}
