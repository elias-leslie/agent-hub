import { Code } from "lucide-react";
import { ModelPill } from "@/app/sessions/components/ModelPill";
import { StatusBadge } from "./StatusBadge";
import { MetricCell } from "./MetricCell";
import { AgentActionsMenu } from "./AgentActionsMenu";
import { cn } from "@/lib/utils";
import type { Agent, AgentMetrics } from "../lib/types";

export function AgentRow({
  agent,
  metrics,
  onClone,
  onArchive,
  onToggleCoding,
}: {
  agent: Agent;
  metrics: AgentMetrics | null;
  onClone: (agent: Agent) => void;
  onArchive: (agent: Agent) => void;
  onToggleCoding?: (agent: Agent) => void;
}) {
  return (
    <div className="grid grid-cols-[180px_1fr_100px_70px_130px_130px_130px_80px_40px] gap-3 px-4 py-3 items-center hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors">
      {/* Agent Name & Slug */}
      <div className="min-w-0">
        <a
          href={`/agents/${agent.slug}`}
          className="text-sm font-semibold text-slate-800 dark:text-slate-100 hover:text-blue-600 dark:hover:text-blue-400 truncate block"
        >
          {agent.name}
        </a>
        <span className="text-[10px] text-slate-400 font-mono">
          {agent.slug}
        </span>
      </div>

      {/* Model Stack */}
      <div className="flex flex-wrap gap-1 items-center">
        <ModelPill model={agent.primary_model_id} />
        {agent.fallback_models.length > 0 && (
          <span className="text-[10px] text-slate-400">
            +{agent.fallback_models.length} fallback
          </span>
        )}
      </div>

      {/* Status */}
      <StatusBadge isActive={agent.is_active} />

      {/* Coding Agent Toggle */}
      <button
        onClick={() => onToggleCoding?.(agent)}
        className={cn(
          "flex items-center justify-center w-8 h-8 rounded-md transition-colors",
          agent.is_coding_agent
            ? "bg-cyan-100 dark:bg-cyan-950/50 text-cyan-600 dark:text-cyan-400"
            : "bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-600 hover:text-slate-500"
        )}
        title={agent.is_coding_agent ? "Coding agent (click to disable)" : "Not a coding agent (click to enable)"}
      >
        <Code className="h-4 w-4" />
      </button>

      {/* Requests 24h with sparkline */}
      <MetricCell
        label="Requests"
        value={metrics?.requests_24h ?? 0}
        trend={metrics?.latency_trend}
        color="blue"
      />

      {/* Latency with sparkline */}
      <MetricCell
        label="Latency"
        value={metrics?.avg_latency_ms?.toFixed(0) ?? "—"}
        unit="ms"
        trend={metrics?.latency_trend}
        color="amber"
      />

      {/* Success Rate with sparkline */}
      <MetricCell
        label="Success"
        value={metrics?.success_rate?.toFixed(1) ?? "100.0"}
        unit="%"
        trend={metrics?.success_trend}
        color="emerald"
      />

      {/* Version */}
      <div className="text-right">
        <span className="text-xs font-mono tabular-nums text-slate-500">
          v{agent.version}
        </span>
      </div>

      {/* Actions */}
      <AgentActionsMenu
        agent={agent}
        onClone={onClone}
        onArchive={onArchive}
      />
    </div>
  );
}
