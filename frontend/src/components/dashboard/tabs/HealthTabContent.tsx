import { Layers, Zap, Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatNumber, formatLatency } from "@/lib/formatters";
import type { DashboardStatsResponse } from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// SYSTEM HEALTH TAB CONTENT
// ─────────────────────────────────────────────────────────────────────────────

export function HealthTabContent({ stats, status }: { stats: DashboardStatsResponse | undefined; status: any }) {
  if (!stats) return <div className="h-48 bg-slate-800 rounded animate-pulse" />;

  return (
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
              <span className="text-slate-100 font-mono">{stats.memory.total_injections > 0 ? `${(stats.requests.success_rate * 100).toFixed(1)}%` : "0%"}</span>
            </div>
            <div className="h-1 bg-slate-700 rounded-full overflow-hidden">
              <div className="h-full bg-emerald-500" style={{ width: `${stats.requests.success_rate * 100}%` }} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 mt-2">
            <div className="p-2 rounded bg-slate-900/50 border border-slate-800">
              <p className="text-[9px] text-slate-500 uppercase">Mandates</p>
              <p className="text-xs font-mono font-bold text-slate-200">{formatNumber(stats.memory.total_mandates)}</p>
            </div>
            <div className="p-2 rounded bg-slate-900/50 border border-slate-800">
              <p className="text-[9px] text-slate-500 uppercase">Latency</p>
              <p className="text-xs font-mono font-bold text-slate-200">{formatLatency(stats.memory.avg_latency_ms)}</p>
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
            <p className="text-3xl font-mono font-bold text-slate-100">{stats.truncations.truncation_rate.toFixed(1)}%</p>
            <p className="text-[10px] text-slate-500 uppercase mt-1">Truncation Rate</p>
          </div>
          <div className="mt-4 pt-4 border-t border-slate-800 flex justify-between">
            <div className="text-center flex-1">
              <p className="text-xs font-mono font-bold text-slate-200">{stats.truncations.total_truncations}</p>
              <p className="text-[8px] text-slate-500 uppercase">Events</p>
            </div>
            <div className="text-center flex-1 border-l border-slate-800">
              <p className="text-xs font-mono font-bold text-slate-200">{stats.truncations.avg_output_tokens.toFixed(0)}</p>
              <p className="text-[8px] text-slate-500 uppercase">Avg Tokens</p>
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
          {status?.circuit_breakers ? Object.entries(status.circuit_breakers).map(([name, info]: [string, any]) => (
            <div key={name} className="flex items-center justify-between p-2 rounded bg-slate-900/50 border border-slate-800">
              <div>
                <p className="text-[10px] font-medium text-slate-300 capitalize">{name}</p>
                <p className="text-[9px] text-slate-500">Failures: {info.consecutive_failures}</p>
              </div>
              <div className={cn(
                "px-2 py-0.5 rounded-full text-[9px] font-bold uppercase",
                info.state === "closed" ? "bg-emerald-500/10 text-emerald-400" :
                  info.state === "open" ? "bg-red-500/10 text-red-400 animate-pulse" : "bg-amber-500/10 text-amber-400"
              )}>
                {info.state}
              </div>
            </div>
          )) : (
            <div className="col-span-2 flex items-center justify-center h-20 text-slate-500 text-xs">
              All systems nominal
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
