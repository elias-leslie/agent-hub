import { History, RefreshCw, Search, TrendingUp, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SessionsCountTriplet } from "../types";
import { formatCost, formatTokens } from "../utils";

export function SessionsHeader({
  counts,
  pageStats,
  searchQuery,
  statusFilter,
  hideBenchmarkTraffic,
  hiddenBenchmarkCount,
  isRefreshing,
  onSearchChange,
  onStatusFilterChange,
  onHideBenchmarkTrafficChange,
  onRefresh,
}: {
  counts: SessionsCountTriplet;
  pageStats: { totalTokens: number; totalCost: number } | null;
  searchQuery: string;
  statusFilter: string;
  hideBenchmarkTraffic: boolean;
  hiddenBenchmarkCount: number;
  isRefreshing: boolean;
  onSearchChange: (value: string) => void;
  onStatusFilterChange: (value: string) => void;
  onHideBenchmarkTrafficChange: (value: boolean) => void;
  onRefresh: () => void;
}) {
  const countCards = [
    { label: "Visible", value: counts.visible, testId: "sessions-visible-count" },
    { label: "Loaded", value: counts.loaded, testId: "sessions-loaded-count" },
    { label: "Total", value: counts.total, testId: "sessions-total-count" },
  ];

  return (
    <header className="page-header border-b border-slate-800/80 bg-slate-950/95 backdrop-blur-xl">
      <div className="page-container px-4 lg:px-8">
        <div className="flex flex-col gap-4 py-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0 space-y-4">
              <div className="flex items-start gap-3">
                <div className="page-title-icon border border-slate-800 bg-slate-900/80 text-slate-200">
                  <History className="h-5 w-5" />
                </div>
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-3">
                    <h1 className="page-title">Sessions ledger</h1>
                    <span
                      data-testid="sessions-filter-scope"
                      className="inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[10px] font-mono uppercase tracking-[0.2em] text-amber-200"
                    >
                      Filter scope: loaded subset
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-sm text-slate-400">
                    <span>Visible rows are filtered client-side from fetched pages.</span>
                    <span className="text-slate-600">•</span>
                    <span>Search and filters apply to loaded rows only.</span>
                  </div>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-3 xl:max-w-3xl">
                {countCards.map((card) => (
                  <div
                    key={card.label}
                    className="rounded-2xl border border-slate-800 bg-slate-900/70 px-4 py-3 shadow-[0_0_0_1px_rgba(15,23,42,0.35)]"
                  >
                    <div className="text-[10px] font-mono uppercase tracking-[0.24em] text-slate-500">
                      {card.label}
                    </div>
                    <div
                      data-testid={card.testId}
                      className="mt-2 text-2xl font-semibold tabular-nums text-slate-100"
                    >
                      {card.value}
                    </div>
                  </div>
                ))}
              </div>

              {pageStats && (
                <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-xs text-slate-300">
                  <span className="inline-flex items-center gap-1.5 text-emerald-300">
                    <Zap className="h-3.5 w-3.5" />
                    Visible tokens {formatTokens(pageStats.totalTokens)}
                  </span>
                  <span className="inline-flex items-center gap-1.5 text-amber-300">
                    <TrendingUp className="h-3.5 w-3.5" />
                    Visible cost {formatCost(pageStats.totalCost)}
                  </span>
                </div>
              )}
            </div>

            <div className="flex w-full flex-col gap-3 xl:max-w-xl">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
                  <input
                    type="text"
                    placeholder="Search loaded subset…"
                    value={searchQuery}
                    onChange={(e) => onSearchChange(e.target.value)}
                    className="control-input w-full py-2.5 pl-9"
                  />
                </div>

                <select
                  data-testid="filter-status"
                  value={statusFilter}
                  onChange={(e) => onStatusFilterChange(e.target.value)}
                  className="control-select cursor-pointer"
                >
                  <option value="">All status</option>
                  <option value="active">Active</option>
                  <option value="completed">Completed</option>
                  <option value="failed">Failed</option>
                </select>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  data-testid="toggle-benchmark-traffic"
                  onClick={() => onHideBenchmarkTrafficChange(!hideBenchmarkTraffic)}
                  className={cn(
                    "rounded-xl border px-3 py-2 text-xs font-medium transition-colors",
                    hideBenchmarkTraffic
                      ? "border-amber-500/30 bg-amber-500/10 text-amber-200"
                      : "border-slate-700 bg-slate-900/60 text-slate-400 hover:text-slate-200",
                  )}
                >
                  {hideBenchmarkTraffic ? "Hidden" : "Showing"} benchmark traffic
                  {hiddenBenchmarkCount > 0 && ` (${hiddenBenchmarkCount})`}
                </button>

                <button
                  type="button"
                  onClick={onRefresh}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs font-medium text-slate-200 transition-colors hover:border-slate-600 hover:bg-slate-900"
                >
                  <RefreshCw
                    className={cn(
                      "h-3.5 w-3.5",
                      isRefreshing && "animate-spin text-emerald-400",
                    )}
                  />
                  Refresh ledger
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
