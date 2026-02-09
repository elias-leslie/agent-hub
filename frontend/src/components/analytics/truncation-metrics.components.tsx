import { Gauge, TrendingUp, Clock, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  TruncationMetrics,
  TruncationAggregation,
  SeverityStyles,
} from "./truncation-metrics.types";
import { formatNumber, formatPercent, formatTime } from "./truncation-metrics.utils";

interface CompactViewProps {
  metrics: TruncationMetrics;
  styles: SeverityStyles;
  className?: string;
}

export function CompactView({ metrics, styles, className }: CompactViewProps) {
  return (
    <div
      className={cn(
        "px-4 py-3 rounded-xl border transition-all duration-300",
        "bg-gradient-to-br",
        styles.bg,
        styles.border,
        "hover:shadow-md",
        styles.glow,
        className,
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Gauge className={cn("h-4 w-4", styles.accent)} />
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
            Truncation Rate
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={cn(
              "text-lg font-bold font-mono tabular-nums",
              styles.accent,
            )}
          >
            {formatPercent(metrics.truncation_rate)}
          </span>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {formatNumber(metrics.total_truncations)} total
          </span>
        </div>
      </div>
    </div>
  );
}

interface StatsGridProps {
  metrics: TruncationMetrics;
  days: number;
  styles: SeverityStyles;
}

export function StatsGrid({ metrics, days, styles }: StatsGridProps) {
  return (
    <div className="grid grid-cols-3 gap-4 mb-4">
      {/* Truncation rate */}
      <div className="space-y-1">
        <div className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
          <TrendingUp className="h-3 w-3" />
          Rate
        </div>
        <div
          className={cn(
            "text-2xl font-bold font-mono tabular-nums",
            styles.accent,
          )}
        >
          {formatPercent(metrics.truncation_rate)}
        </div>
      </div>

      {/* Total truncations */}
      <div className="space-y-1">
        <div className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
          <AlertTriangle className="h-3 w-3" />
          Total
        </div>
        <div className="text-2xl font-bold font-mono tabular-nums text-slate-700 dark:text-slate-300">
          {formatNumber(metrics.total_truncations)}
        </div>
      </div>

      {/* Time period */}
      <div className="space-y-1">
        <div className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
          <Clock className="h-3 w-3" />
          Period
        </div>
        <div className="text-2xl font-bold font-mono tabular-nums text-slate-700 dark:text-slate-300">
          {days}d
        </div>
      </div>
    </div>
  );
}

interface ModelBreakdownProps {
  aggregations: TruncationAggregation[];
}

export function ModelBreakdown({ aggregations }: ModelBreakdownProps) {
  if (aggregations.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
        By Model
      </div>
      <div className="space-y-1.5">
        {aggregations.slice(0, 3).map((agg) => (
          <div
            key={agg.group_key}
            className="flex items-center justify-between py-1.5 px-2 rounded-md bg-slate-100/50 dark:bg-slate-800/30"
          >
            <span className="text-xs font-mono text-slate-600 dark:text-slate-400 truncate max-w-[120px]">
              {agg.group_key}
            </span>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono tabular-nums text-slate-700 dark:text-slate-300">
                {formatNumber(agg.truncation_count)}
              </span>
              {agg.capped_count > 0 && (
                <span className="text-[9px] px-1 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400">
                  {agg.capped_count} capped
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface RecentEventsProps {
  events: TruncationMetrics["recent_events"];
}

export function RecentEvents({ events }: RecentEventsProps) {
  if (events.length === 0) return null;

  return (
    <div className="mt-4 pt-3 border-t border-slate-200/50 dark:border-slate-700/30">
      <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">
        Recent Events
      </div>
      <div className="space-y-1">
        {events.slice(0, 3).map((event) => (
          <div
            key={event.id}
            className="flex items-center justify-between text-[11px]"
          >
            <div className="flex items-center gap-2">
              <span className="text-slate-400 dark:text-slate-500">
                {formatTime(event.created_at)}
              </span>
              <span className="font-mono text-slate-600 dark:text-slate-400 truncate max-w-[100px]">
                {event.model.split("-").slice(-2).join("-")}
              </span>
            </div>
            <span className="font-mono tabular-nums text-slate-500 dark:text-slate-400">
              {formatNumber(event.output_tokens)}/
              {formatNumber(event.max_tokens_requested)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
