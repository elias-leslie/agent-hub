"use client";

import { Gauge, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TruncationMetricsWidgetProps } from "./truncation-metrics.types";
import { useTruncationMetrics } from "./truncation-metrics.hooks";
import {
  getSeverityLevel,
  severityStyles,
} from "./truncation-metrics.utils";
import {
  CompactView,
  StatsGrid,
  ModelBreakdown,
  RecentEvents,
} from "./truncation-metrics.components";

/**
 * Dashboard widget displaying truncation analytics.
 * Industrial/mission-control aesthetic with real-time data.
 */
export function TruncationMetricsWidget({
  className,
  compact = false,
  days = 7,
}: TruncationMetricsWidgetProps) {
  const { metrics, loading, error, lastUpdated, fetchMetrics } =
    useTruncationMetrics(days);

  if (loading && !metrics) {
    return (
      <div className={cn("animate-pulse", className)}>
        <div className="h-40 bg-slate-100 dark:bg-slate-800 rounded-xl" />
      </div>
    );
  }

  if (error) {
    return (
      <div
        className={cn(
          "p-4 rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30",
          className,
        )}
      >
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        <button
          onClick={fetchMetrics}
          className="mt-2 text-xs text-red-500 hover:text-red-600 underline"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!metrics) return null;

  const severity = getSeverityLevel(metrics.truncation_rate);
  const styles = severityStyles[severity];

  if (compact) {
    return <CompactView metrics={metrics} styles={styles} className={className} />;
  }

  return (
    <div
      className={cn(
        "rounded-xl border overflow-hidden transition-all duration-300",
        "bg-gradient-to-br",
        styles.bg,
        styles.border,
        "hover:shadow-lg",
        styles.glow,
        className,
      )}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-200/50 dark:border-slate-700/30 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="relative">
            <Gauge className={cn("h-5 w-5", styles.accent)} />
            {metrics.truncation_rate > 5 && (
              <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
            )}
          </div>
          <h3 className="font-semibold text-slate-800 dark:text-slate-200">
            Truncation Monitor
          </h3>
        </div>
        <div className="flex items-center gap-2">
          {lastUpdated && (
            <span className="text-[10px] text-slate-400 dark:text-slate-500">
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchMetrics}
            disabled={loading}
            className={cn(
              "p-1 rounded hover:bg-slate-200/50 dark:hover:bg-slate-700/50 transition-colors",
              loading && "animate-spin",
            )}
          >
            <RefreshCw className="h-3.5 w-3.5 text-slate-400" />
          </button>
        </div>
      </div>

      {/* Main stats */}
      <div className="p-4">
        <StatsGrid metrics={metrics} days={days} styles={styles} />
        <ModelBreakdown aggregations={metrics.aggregations} />
        <RecentEvents events={metrics.recent_events} />
      </div>
    </div>
  );
}
