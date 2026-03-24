import { Server, Cpu } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatLatency } from "@/lib/formatters";
import type { ProviderStatus } from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// PROVIDER STATUS - Compact inline display
// ─────────────────────────────────────────────────────────────────────────────

export function ProviderStatusCard({ provider }: { provider: ProviderStatus }) {
  const health = provider.health;
  const state = health?.state || (provider.available ? "healthy" : "unavailable");

  const stateConfig = {
    healthy: { color: "text-emerald-500", bg: "bg-emerald-500/10", label: "Healthy", dot: "bg-emerald-500" },
    degraded: { color: "text-amber-500", bg: "bg-amber-500/10", label: "Degraded", dot: "bg-amber-500" },
    unavailable: { color: "text-red-500", bg: "bg-red-500/10", label: "Down", dot: "bg-red-500" },
    unknown: { color: "text-slate-400", bg: "bg-slate-400/10", label: "Unknown", dot: "bg-slate-400" },
  };

  const config = stateConfig[state] || stateConfig.unknown;

  return (
    <div className="flex items-center justify-between p-3 rounded-lg bg-slate-800/30 border border-slate-800/50">
      <div className="flex items-center gap-3">
        <div className={cn("p-1.5 rounded-md", config.bg)}>
          {provider.name === "claude" ? (
            <Cpu className="h-4 w-4 text-orange-400" />
          ) : (
            <Server className="h-4 w-4 text-amber-400" />
          )}
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-100 capitalize">
              {provider.name}
            </span>
            <span className={cn("w-1.5 h-1.5 rounded-full", config.dot, state === "healthy" && "animate-pulse")} />
          </div>
          {health && (
            <div className="flex items-center gap-2 mt-0.5 text-[10px] text-slate-400 font-mono">
              <span>{formatLatency(health.latency_ms)}</span>
              <span className="text-slate-700">|</span>
              <span>{(health.availability * 100).toFixed(0)}% avail</span>
            </div>
          )}
        </div>
      </div>
      <span className={cn("text-[10px] font-medium uppercase tracking-wide px-2 py-0.5 rounded", config.bg, config.color)}>
        {config.label}
      </span>
    </div>
  );
}
