"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Gauge,
  TrendingUp,
  Clock,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface TruncationAggregation {
  group_key: string;
  truncation_count: number;
  avg_output_tokens: number;
  avg_max_tokens: number;
  capped_count: number;
}

interface TruncationMetrics {
  aggregations: TruncationAggregation[];
  total_truncations: number;
  truncation_rate: number;
  recent_events: Array<{
    id: number;
    model: string;
    endpoint: string;
    output_tokens: number;
    max_tokens_requested: number;
    model_limit: number;
    was_capped: boolean;
    created_at: string;
  }>;
}

interface TruncationMetricsWidgetProps {
  className?: string;
  compact?: boolean;
  days?: number;
}

/**
 * Dashboard widget displaying truncation analytics.
 * Industrial/mission-control aesthetic with real-time data.
 */
export function TruncationMetricsWidget({
  className,
  compact = false,
  days = 7,
}: TruncationMetricsWidgetProps) {
  const [metrics, setMetrics] = useState<TruncationMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchMetrics = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(
        `/api/analytics/truncations?days=${days}&group_by=model&include_recent=true&limit_recent=5`,
      );
      if (!response.ok) throw new Error("Failed to fetch metrics");
      const data = await response.json();
      setMetrics(data);
      setLastUpdated(new Date());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    fetchMetrics();
    // Auto-refresh every 5 minutes
    const interval = setInterval(fetchMetrics, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [days, fetchMetrics]);

  const formatNumber = (n: number) => n.toLocaleString();
  const formatPercent = (n: number) => `${n.toFixed(1)}%`;
  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

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

  // Determine severity level based on truncation rate
  const severity =
    metrics.truncation_rate > 10
      ? "high"
      : metrics.truncation_rate > 5
        ? "medium"
        : "low";

  const severityStyles = {
    low: {
      bg: "from-emerald-50 to-teal-50/50 dark:from-emerald-950/30 dark:to-teal-950/20",
      border: "border-emerald-200/60 dark:border-emerald-800/40",
      accent: "text-emerald-600 dark:text-emerald-400",
      glow: "shadow-emerald-100 dark:shadow-emerald-900/20",
    },
    medium: {
      bg: "from-amber-50 to-orange-50/50 dark:from-amber-950/30 dark:to-orange-950/20",
      border: "border-amber-200/60 dark:border-amber-800/40",
      accent: "text-amber-600 dark:text-amber-400",
      glow: "shadow-amber-100 dark:shadow-amber-900/20",
    },
    high: {
      bg: "from-rose-50 to-red-50/50 dark:from-rose-950/30 dark:to-red-950/20",
      border: "border-rose-200/60 dark:border-rose-800/40",
      accent: "text-rose-600 dark:text-rose-400",
      glow: "shadow-rose-100 dark:shadow-rose-900/20",
    },
  };

  const styles = severityStyles[severity];

  if (compact) {
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

        {/* By model breakdown */}
        {metrics.aggregations.length > 0 && (
          <div className="space-y-2">
            <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
              By Model
            </div>
            <div className="space-y-1.5">
              {metrics.aggregations.slice(0, 3).map((agg) => (
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
        )}

        {/* Recent events */}
        {metrics.recent_events.length > 0 && (
          <div className="mt-4 pt-3 border-t border-slate-200/50 dark:border-slate-700/30">
            <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">
              Recent Events
            </div>
            <div className="space-y-1">
              {metrics.recent_events.slice(0, 3).map((event) => (
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
        )}
      </div>
    </div>
  );
}
