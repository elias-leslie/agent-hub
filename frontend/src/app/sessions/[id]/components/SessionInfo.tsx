import { Cpu, Activity, Clock, Layers } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Session } from "@/lib/api";
import type { SessionMemoryObservability } from "@/lib/session-memory-observability";
import { formatDate, formatTokens } from "./utils";
import { ContextUsageBar } from "./ContextUsageBar";
import { StatCard } from "./StatCard";

interface SessionInfoProps {
  session: Session;
  memorySummary?: SessionMemoryObservability | null;
}

export function SessionInfo({ session, memorySummary }: SessionInfoProps) {
  return (
    <div className="p-6 max-w-4xl space-y-6">
      {/* Context Usage */}
      {session.context_usage && (
        <ContextUsageBar usage={session.context_usage} />
      )}

      {/* Session Info Grid */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard icon={Layers} label="Project" value={session.project_id} />
        <StatCard
          icon={Cpu}
          label="Provider"
          value={session.provider}
          subValue={session.model}
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

      {/* Token breakdown */}
      {session.agent_token_breakdown &&
        session.agent_token_breakdown.length > 0 && (
          <div
            className={cn(
              "p-4 rounded-lg",
              "bg-slate-900/60 border border-slate-800/60"
            )}
          >
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
                      {formatTokens(agent.input_tokens)} in /{" "}
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
              "p-4 rounded-lg text-center",
              "bg-sky-950/30 border border-sky-800/40"
            )}
          >
            <p className="text-2xl font-mono font-semibold text-sky-400">
              {formatTokens(session.total_input_tokens || 0)}
            </p>
            <p className="text-xs text-sky-500 mt-1">Input Tokens</p>
          </div>
          <div
            className={cn(
              "p-4 rounded-lg text-center",
              "bg-violet-950/30 border border-violet-800/40"
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
  );
}
