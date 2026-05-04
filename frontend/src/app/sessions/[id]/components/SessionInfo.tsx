import { Activity, Clock, Cpu, Layers } from 'lucide-react'
import type { Session } from '@/lib/api'
import type { SessionMemoryObservability } from '@/lib/session-memory-observability'
import { cn } from '@/lib/utils'
import { ContextUsageBar } from './ContextUsageBar'
import { StatCard } from './StatCard'
import { formatDate, formatTokens } from './utils'

interface SessionInfoProps {
  session: Session
  memorySummary?: SessionMemoryObservability | null
}

export function SessionInfo({ session, memorySummary }: SessionInfoProps) {
  const requestedModel = session.requested_model || session.model
  const effectiveModel = session.effective_model || session.model
  const requestedProvider = session.requested_provider || session.provider
  const effectiveProvider = session.effective_provider || session.provider
  const fallbackDetail =
    session.fallback_used && requestedModel !== effectiveModel
      ? `${requestedProvider}/${requestedModel} -> ${effectiveProvider}/${effectiveModel}`
      : effectiveModel
  const live = session.live_activity

  return (
    <div className="space-y-6 p-5 lg:p-6">
      <div className="section-header gap-4">
        <div>
          <p className="section-kicker">Session Intel</p>
          <h2 className="section-heading mt-2">Execution Summary</h2>
          <p className="section-copy mt-2 max-w-3xl">
            Review the provider fallback path, context pressure, token totals,
            and any live health signals captured for this session.
          </p>
        </div>
      </div>

      {/* Context Usage */}
      {session.context_usage && (
        <ContextUsageBar usage={session.context_usage} />
      )}

      {/* Session Info Grid */}
      <div className="detail-grid">
        <StatCard icon={Layers} label="Project" value={session.project_id} />
        {session.attribution_label && (
          <StatCard
            icon={Layers}
            label="Attribution"
            value={session.attribution_label}
            subValue={session.attribution_detail || undefined}
          />
        )}
        <StatCard
          icon={Cpu}
          label="Provider"
          value={effectiveProvider}
          subValue={fallbackDetail}
        />
        <StatCard icon={Activity} label="Type" value={session.session_type} />
        <StatCard
          icon={Clock}
          label="Updated"
          value={formatDate(session.updated_at)}
        />
        {memorySummary && (
          <StatCard
            icon={Layers}
            label="References"
            value={`${memorySummary.selectedCount} selected / ${memorySummary.indexCount} index`}
            subValue={`selected cited ${memorySummary.selectedCitedCount}/${memorySummary.selectedCount} (${memorySummary.selectedCitationRate}%)`}
          />
        )}
      </div>

      {live && (
        <div
          className={cn(
            'section-card',
            live.health === 'stalled'
              ? 'bg-red-950/20 border border-red-800/40'
              : live.health === 'quiet'
                ? 'bg-amber-950/20 border border-amber-800/40'
                : 'bg-slate-900/60 border border-slate-800/60',
          )}
        >
          <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
            <span className="text-slate-300">
              {live.health} · {live.phase}
            </span>
            {live.current_tool_name && (
              <span className="text-sky-400">
                tool {live.current_tool_name}
              </span>
            )}
            {live.quiet_for_seconds !== null &&
              live.quiet_for_seconds !== undefined && (
                <span className="text-slate-500">
                  quiet {live.quiet_for_seconds}s
                </span>
              )}
            <span className="text-slate-500">
              tools {live.tool_calls_count}
            </span>
          </div>
          {live.summary && (
            <p className="mt-2 text-sm text-slate-300">{live.summary}</p>
          )}
          {(live.stall_reason ||
            live.last_command ||
            live.last_validation_command ||
            live.last_read_path ||
            live.last_write_path) && (
            <div className="mt-3 space-y-1 text-xs font-mono text-slate-400 break-all">
              {live.stall_reason && <p>{live.stall_reason}</p>}
              {live.last_validation_command && (
                <p>validation: {live.last_validation_command}</p>
              )}
              {!live.last_validation_command && live.last_command && (
                <p>command: {live.last_command}</p>
              )}
              {live.last_read_path && <p>read: {live.last_read_path}</p>}
              {live.last_write_path && <p>write: {live.last_write_path}</p>}
            </div>
          )}
        </div>
      )}

      {session.fallback_used && session.fallback_reason && (
        <div
          className={cn(
            'section-card',
            'bg-amber-950/20 border border-amber-800/40',
          )}
        >
          <h3 className="text-sm font-medium text-amber-300 mb-1">
            Fallback Reason
          </h3>
          <p className="text-sm text-amber-100/80 font-mono break-words">
            {session.fallback_reason}
          </p>
        </div>
      )}

      {/* Token breakdown */}
      {session.agent_token_breakdown &&
        session.agent_token_breakdown.length > 0 && (
          <div className={cn('section-card')}>
            <h3 className="text-sm font-medium text-slate-300 mb-3">
              Token Breakdown by Agent
            </h3>
            <div className="space-y-2">
              {session.agent_token_breakdown.map((agent) => (
                <div
                  key={agent.agent_id}
                  className="flex items-center justify-between py-2 border-b border-slate-800/40 last:border-0"
                >
                  <div>
                    <p className="text-sm text-slate-300">
                      {agent.agent_name || agent.agent_id}
                    </p>
                    <p className="text-xs text-slate-500">
                      {agent.message_count} messages
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-mono text-slate-300">
                      {formatTokens(agent.total_tokens)}
                    </p>
                    <p className="text-xs text-slate-500 font-mono">
                      {formatTokens(agent.input_tokens)} in /{' '}
                      {formatTokens(agent.output_tokens)} out
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

      {/* Totals */}
      {(session.total_input_tokens || session.total_output_tokens) && (
        <div className="grid grid-cols-2 gap-3">
          <div
            className={cn(
              'section-card text-center',
              'bg-sky-950/30 border border-sky-800/40',
            )}
          >
            <p className="text-2xl font-mono font-semibold text-sky-400">
              {formatTokens(session.total_input_tokens || 0)}
            </p>
            <p className="text-xs text-sky-500 mt-1">Input Tokens</p>
          </div>
          <div
            className={cn(
              'section-card text-center',
              'bg-violet-950/30 border border-violet-800/40',
            )}
          >
            <p className="text-2xl font-mono font-semibold text-violet-400">
              {formatTokens(session.total_output_tokens || 0)}
            </p>
            <p className="text-xs text-violet-500 mt-1">Output Tokens</p>
          </div>
        </div>
      )}
    </div>
  )
}
