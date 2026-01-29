import { Terminal } from "lucide-react";
import { cn } from "@/lib/utils";
import { ToolNameMetric } from "../types";
import { formatNumber, formatLatency } from "../utils";

export function TopTools({ data }: { data: ToolNameMetric[] }) {
  if (data.length === 0) {
    return (
      <div className="text-sm text-slate-500 text-center py-4">
        No tool usage data yet. CLI commands will appear here.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {data.slice(0, 5).map((tool, idx) => (
        <div
          key={tool.tool_name}
          className="flex items-center gap-3 p-2 rounded-lg bg-slate-800/30 hover:bg-slate-800/50 transition-colors"
        >
          <span className="text-xs font-mono text-slate-500 w-4">{idx + 1}</span>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-mono text-cyan-300 truncate">{tool.tool_name}</p>
            <div className="flex items-center gap-3 mt-0.5 text-[10px] text-slate-500">
              <span>{formatNumber(tool.count)} calls</span>
              <span className={cn(
                tool.success_rate >= 95 ? "text-emerald-400" :
                tool.success_rate >= 80 ? "text-amber-400" : "text-red-400"
              )}>
                {tool.success_rate.toFixed(0)}% success
              </span>
              <span>{formatLatency(tool.avg_latency_ms)}</span>
            </div>
          </div>
          <Terminal className="h-3 w-3 text-slate-600" />
        </div>
      ))}
    </div>
  );
}
