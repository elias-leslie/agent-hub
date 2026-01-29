import { cn } from "@/lib/utils";
import { ToolTypeBreakdown } from "../types";
import { formatNumber } from "../utils";

export function ToolTypeDistribution({ data }: { data: ToolTypeBreakdown[] }) {
  const total = data.reduce((sum, d) => sum + d.count, 0);
  if (total === 0) return null;

  const colors = {
    api: "bg-blue-500",
    cli: "bg-emerald-500",
    sdk: "bg-purple-500",
  };

  return (
    <div className="space-y-3">
      {/* Bar visualization */}
      <div className="h-2 rounded-full bg-slate-800 overflow-hidden flex">
        {data.map((item) => {
          const pct = (item.count / total) * 100;
          const colorKey = item.tool_type?.toLowerCase() as keyof typeof colors;
          return (
            <div
              key={item.tool_type}
              className={cn("h-full transition-all duration-500", colors[colorKey] || "bg-slate-600")}
              style={{ width: `${pct}%` }}
            />
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4">
        {data.map((item) => {
          const pct = ((item.count / total) * 100).toFixed(0);
          const colorKey = item.tool_type?.toLowerCase() as keyof typeof colors;
          return (
            <div key={item.tool_type} className="flex items-center gap-2">
              <span className={cn("w-2 h-2 rounded-full", colors[colorKey] || "bg-slate-600")} />
              <span className="text-xs text-slate-400">
                {item.tool_type?.toUpperCase() || "API"}: {formatNumber(item.count)} ({pct}%)
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
