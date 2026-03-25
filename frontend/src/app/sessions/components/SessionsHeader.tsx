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
    <header className="page-header">
      <div className="page-container px-4 lg:px-8">
        <div className="page-header-row">
          <div className="page-title-group">
            <div className="page-title-icon">
              <History className="h-5 w-5" />
            </div>
            <div className="page-title-stack">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="page-title">Sessions</h1>
                <span className="page-pill">{total} total</span>
                {pageStats && (
                  <>
                    <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
                      <Zap className="h-3 w-3" />
                      {formatTokens(pageStats.totalTokens)}
                    </span>
                    <span className="inline-flex items-center gap-1 text-xs text-amber-300">
                      <TrendingUp className="h-3 w-3" />
                      {formatCost(pageStats.totalCost)}
                    </span>
                  </>
                )}
              </div>
              <div className="page-meta">
                <span>Track live and historical sessions, inspect token spend, and jump into detailed timelines.</span>
              </div>
            </div>
          </div>

          <div className="page-toolbar">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
              <input
                type="text"
                placeholder="Search..."
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
                className="control-input w-56 py-2 pl-9"
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
              <option value="error">Error</option>
            </select>

            <button
              onClick={onRefresh}
              className="icon-button"
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
