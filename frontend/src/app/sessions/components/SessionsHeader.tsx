import { Search, RefreshCw, Zap, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { REFRESH_OPTIONS, type RefreshInterval } from "../types";
import { formatCost, formatTokens } from "../utils";

export function SessionsHeader({
  total,
  pageStats,
  searchQuery,
  statusFilter,
  projectFilter,
  refreshInterval,
  isRefreshing,
  showLiveView,
  wsStatus,
  onSearchChange,
  onStatusFilterChange,
  onProjectFilterChange,
  onRefreshChange,
  onToggleLiveView,
}: {
  total: number;
  pageStats: { totalTokens: number; totalCost: number } | null;
  searchQuery: string;
  statusFilter: string;
  projectFilter: string;
  refreshInterval: RefreshInterval;
  isRefreshing: boolean;
  showLiveView: boolean;
  wsStatus: string;
  onSearchChange: (value: string) => void;
  onStatusFilterChange: (value: string) => void;
  onProjectFilterChange: (value: string) => void;
  onRefreshChange: (interval: RefreshInterval) => void;
  onToggleLiveView: () => void;
}) {
  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
      <div className="px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100 tracking-tight">
              Sessions
            </h1>
            <div className="flex items-center gap-3 text-xs font-mono tabular-nums">
              <span className="text-slate-500 dark:text-slate-400">
                {total} total
              </span>
              {pageStats && (
                <>
                  <span className="text-slate-300 dark:text-slate-600">|</span>
                  <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                    <Zap className="h-3 w-3" />
                    {formatTokens(pageStats.totalTokens)}
                  </span>
                  <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400">
                    <TrendingUp className="h-3 w-3" />
                    {formatCost(pageStats.totalCost)}
                  </span>
                </>
              )}
            </div>
          </div>

          {/* Controls */}
          <div className="flex items-center gap-2">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
              <input
                type="text"
                placeholder="Search..."
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
                className="pl-8 pr-3 py-1.5 w-36 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500"
              />
            </div>

            {/* Status Filter */}
            <select
              data-testid="filter-status"
              value={statusFilter}
              onChange={(e) => onStatusFilterChange(e.target.value)}
              className="px-2.5 py-1.5 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500/40"
            >
              <option value="">All status</option>
              <option value="active">Active</option>
              <option value="completed">Completed</option>
              <option value="error">Error</option>
            </select>

            {/* Project Filter */}
            <input
              data-testid="filter-project"
              type="text"
              placeholder="Project..."
              value={projectFilter}
              onChange={(e) => onProjectFilterChange(e.target.value)}
              className="px-2.5 py-1.5 w-24 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500/40"
            />

            {/* Divider */}
            <div className="w-px h-6 bg-slate-200 dark:bg-slate-700" />

            {/* Auto-refresh */}
            <div className="flex items-center gap-1.5">
              <RefreshCw
                className={cn(
                  "h-3.5 w-3.5",
                  isRefreshing
                    ? "animate-spin text-emerald-500"
                    : "text-slate-400"
                )}
              />
              <select
                data-testid="refresh-dropdown"
                value={refreshInterval}
                onChange={(e) => onRefreshChange(parseInt(e.target.value, 10) as RefreshInterval)}
                className={cn(
                  "px-2 py-1.5 rounded-md border text-xs focus:outline-none focus:ring-2 focus:ring-blue-500/40",
                  refreshInterval > 0
                    ? "bg-emerald-50 dark:bg-emerald-900/30 border-emerald-300 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300"
                    : "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700"
                )}
              >
                {REFRESH_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Live View */}
            <button
              onClick={onToggleLiveView}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-semibold transition-colors",
                showLiveView
                  ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 border border-green-300 dark:border-green-800"
                  : "bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700"
              )}
            >
              Live
              {showLiveView && wsStatus === "connected" && (
                <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
              )}
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
