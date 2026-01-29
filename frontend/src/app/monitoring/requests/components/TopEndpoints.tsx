import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { EndpointMetric } from "../types";
import { formatNumber, formatLatency } from "../utils";

export function TopEndpoints({ data }: { data: EndpointMetric[] }) {
  if (data.length === 0) return null;

  return (
    <div className="space-y-2">
      {data.slice(0, 5).map((endpoint, idx) => (
        <div
          key={endpoint.endpoint}
          className="flex items-center gap-3 p-2 rounded-lg bg-slate-800/30 hover:bg-slate-800/50 transition-colors"
        >
          <span className="text-xs font-mono text-slate-500 w-4">{idx + 1}</span>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-mono text-slate-200 truncate">{endpoint.endpoint}</p>
            <div className="flex items-center gap-3 mt-0.5 text-[10px] text-slate-500">
              <span>{formatNumber(endpoint.count)} reqs</span>
              <span className={cn(
                endpoint.success_rate >= 95 ? "text-emerald-400" :
                endpoint.success_rate >= 80 ? "text-amber-400" : "text-red-400"
              )}>
                {endpoint.success_rate.toFixed(0)}% success
              </span>
              <span>{formatLatency(endpoint.avg_latency_ms)}</span>
            </div>
          </div>
          <ArrowUpRight className="h-3 w-3 text-slate-600" />
        </div>
      ))}
    </div>
  );
}
