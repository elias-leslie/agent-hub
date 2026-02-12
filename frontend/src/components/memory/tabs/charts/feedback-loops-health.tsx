import type { MemoryAnalytics, MetricsDashboard } from "@/lib/memory-api";
import { StatusDot } from "../analytics-components";

interface FeedbackLoopsHealthProps {
  analytics: MemoryAnalytics;
  metrics: MetricsDashboard | undefined;
}

function getLoopStatus(value: number): "active" | "warning" | "inactive" {
  if (value > 0) return "active";
  return "inactive";
}

export function FeedbackLoopsHealth({ analytics, metrics }: FeedbackLoopsHealthProps) {
  const loops = [
    {
      name: "Citation Scanning",
      description: "CC hook scans for [M:id]/[G:id]/[R:id] citations",
      stat: `${analytics.total_cited} cited`,
      status: getLoopStatus(analytics.total_cited),
    },
    {
      name: "Task Outcome",
      description: "Task success/failure credited to injected memories",
      stat: `${analytics.total_success} succeeded`,
      status: getLoopStatus(analytics.total_success),
    },
    {
      name: "Utility Scoring",
      description: "3-tier formula: citations + success + recency",
      stat: `${analytics.avg_utility_score.toFixed(2)} avg`,
      status: getLoopStatus(analytics.avg_utility_score),
    },
  ];

  return (
    <div className="space-y-3">
      {loops.map((loop) => (
        <div
          key={loop.name}
          className="flex items-center gap-3 p-3 rounded-lg bg-slate-800/40 border border-slate-800/60"
        >
          <StatusDot status={loop.status} />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-200">{loop.name}</p>
            <p className="text-[10px] text-slate-500 truncate">{loop.description}</p>
          </div>
          <span className="text-xs font-mono text-slate-400 shrink-0">{loop.stat}</span>
        </div>
      ))}
      {metrics && (
        <div className="pt-1 text-[10px] text-slate-500 text-center">
          {metrics.total_injections} total injections tracked
        </div>
      )}
    </div>
  );
}
