import { Search, RefreshCw, Zap, TrendingUp, History } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatCost, formatTokens } from "../utils";

export function SessionsHeader({
  total,
  pageStats,
  searchQuery,
  statusFilter,
  isRefreshing,
  onSearchChange,
  onStatusFilterChange,
  onRefresh,
}: {
  total: number;
  pageStats: { totalTokens: number; totalCost: number } | null;
  searchQuery: string;
  statusFilter: string;
  isRefreshing: boolean;
  onSearchChange: (value: string) => void;
  onStatusFilterChange: (value: string) => void;
  onRefresh: () => void;
}) {
  return (
    <header className="sticky top-0 z-30 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
      <div className="px-6 lg:px-8">
        <div className="flex items-center justify-between h-12">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2.5">
              <History className="h-4.5 w-4.5 text-slate-400" />
              <h1 className="text-base font-semibold text-slate-100 tracking-tight">
                Sessions
              </h1>
            </div>
            <div className="flex items-center gap-3 text-xs font-mono tabular-nums">
              <span className="text-slate-400">
                {total} total
              </span>
              {pageStats && (
                <>
                  <span className="text-slate-600">|</span>
                  <span className="flex items-center gap-1 text-emerald-400">
                    <Zap className="h-3 w-3" />
                    {formatTokens(pageStats.totalTokens)}
                  </span>
                  <span className="flex items-center gap-1 text-amber-400">
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
                className="pl-8 pr-3 py-1.5 w-44 rounded-md border border-slate-700 bg-slate-800 text-xs focus:outline-none focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500"
              />
            </div>

            {/* Status Filter */}
            <select
              data-testid="filter-status"
              value={statusFilter}
              onChange={(e) => onStatusFilterChange(e.target.value)}
              className="px-2.5 py-1.5 rounded-md border border-slate-700 bg-slate-800 text-xs focus:outline-none focus:ring-2 focus:ring-amber-500/40"
            >
              <option value="">All status</option>
              <option value="active">Active</option>
              <option value="completed">Completed</option>
              <option value="error">Error</option>
            </select>

            {/* Refresh */}
            <button
              onClick={onRefresh}
              className="p-1.5 rounded-md border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-400 transition-colors cursor-pointer"
              title="Refresh"
            >
              <RefreshCw
                className={cn(
                  "h-3.5 w-3.5",
                  isRefreshing && "animate-spin text-emerald-500"
                )}
              />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
