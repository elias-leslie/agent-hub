import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import {
  Shield,
  Clock,
  Search,
  X,
  ChevronDown,
  Download,
  Filter,
  Radio,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { SortableHeader, type SortField, type SortDirection } from "./SortableHeader";
import { ExpandedRowContent } from "./ExpandedRowContent";
import { formatRelativeTime, downloadJson } from "../utils";
import type { BlockedRequest } from "../api";

const REFRESH_OPTIONS = [
  { value: 0, label: "Manual" },
  { value: 5000, label: "5s" },
  { value: 15000, label: "15s" },
  { value: 30000, label: "30s" },
] as const;

type RefreshInterval = (typeof REFRESH_OPTIONS)[number]["value"];

export function BlockedRequestsTable({
  requests,
  isLoading,
  onRefresh,
  isRefreshing,
}: {
  requests: BlockedRequest[];
  isLoading: boolean;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  const tableRef = useRef<HTMLDivElement>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [sortField, setSortField] = useState<SortField>("timestamp");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);
  const [focusedRowIndex, setFocusedRowIndex] = useState<number>(-1);
  const [clientFilter, setClientFilter] = useState<string | null>(null);
  const [refreshInterval, setRefreshInterval] = useState<RefreshInterval>(0);

  // Auto-refresh
  useEffect(() => {
    if (refreshInterval === 0) return;
    const intervalId = setInterval(onRefresh, refreshInterval);
    return () => clearInterval(intervalId);
  }, [refreshInterval, onRefresh]);

  // Get unique clients for filter
  const uniqueClients = useMemo(() => {
    const clients = new Set(requests.map((r) => r.client_name).filter(Boolean) as string[]);
    return Array.from(clients).sort();
  }, [requests]);

  // Filter and search
  const filteredRequests = useMemo(() => {
    let filtered = requests;

    // Client filter
    if (clientFilter) {
      filtered = filtered.filter((r) => r.client_name === clientFilter);
    }

    // Search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (r) =>
          r.client_name?.toLowerCase().includes(q) ||
          r.endpoint.toLowerCase().includes(q) ||
          r.block_reason.toLowerCase().includes(q) ||
          r.source_path?.toLowerCase().includes(q)
      );
    }

    return filtered;
  }, [requests, clientFilter, searchQuery]);

  // Sort
  const sortedRequests = useMemo(() => {
    const items = [...filteredRequests];
    items.sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "timestamp":
          cmp = new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
          break;
        case "client_name":
          cmp = (a.client_name || "").localeCompare(b.client_name || "");
          break;
        case "endpoint":
          cmp = a.endpoint.localeCompare(b.endpoint);
          break;
        case "block_reason":
          cmp = a.block_reason.localeCompare(b.block_reason);
          break;
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });
    return items;
  }, [filteredRequests, sortField, sortDirection]);

  const handleSort = useCallback(
    (field: SortField) => {
      const newDirection = sortField === field && sortDirection === "desc" ? "asc" : "desc";
      setSortField(field);
      setSortDirection(newDirection);
    },
    [sortField, sortDirection]
  );

  const handleToggleExpand = useCallback((index: number) => {
    setExpandedIndex((prev) => (prev === index ? null : index));
  }, []);

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!sortedRequests.length) return;

      switch (e.key) {
        case "ArrowDown":
        case "j":
          e.preventDefault();
          setFocusedRowIndex((prev) => Math.min(prev + 1, sortedRequests.length - 1));
          break;
        case "ArrowUp":
        case "k":
          e.preventDefault();
          setFocusedRowIndex((prev) => Math.max(prev - 1, 0));
          break;
        case "Enter":
        case " ":
          e.preventDefault();
          if (focusedRowIndex >= 0 && focusedRowIndex < sortedRequests.length) {
            handleToggleExpand(focusedRowIndex);
          }
          break;
        case "Escape":
          e.preventDefault();
          setExpandedIndex(null);
          break;
      }
    },
    [sortedRequests, focusedRowIndex, handleToggleExpand]
  );

  // Export to JSON
  const handleExport = useCallback(() => {
    const exportData = {
      exported_at: new Date().toISOString(),
      count: sortedRequests.length,
      requests: sortedRequests,
    };
    downloadJson(exportData, `blocked-requests-${new Date().toISOString().split("T")[0]}.json`);
  }, [sortedRequests]);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/30 overflow-hidden">
      {/* Table Controls */}
      <div className="px-4 py-3 border-b border-slate-800 space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px] max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search blocked requests..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-9 py-2 rounded-lg border border-slate-700 bg-slate-800/50 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>

          {/* Client filter */}
          <div className="relative">
            <Filter className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
            <select
              value={clientFilter || ""}
              onChange={(e) => setClientFilter(e.target.value || null)}
              className={cn(
                "pl-9 pr-8 py-2 rounded-lg border text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 appearance-none cursor-pointer",
                clientFilter
                  ? "bg-amber-900/30 border-amber-700 text-amber-300"
                  : "bg-slate-800/50 border-slate-700 text-slate-300"
              )}
            >
              <option value="">All Clients</option>
              {uniqueClients.map((client) => (
                <option key={client} value={client}>
                  {client === "<unknown>" ? "UNKNOWN" : client}
                </option>
              ))}
            </select>
          </div>

          {/* Auto-refresh */}
          <div className="flex items-center gap-1.5">
            <Radio
              className={cn(
                "h-4 w-4",
                refreshInterval > 0 ? "text-amber-400 animate-pulse" : "text-slate-500"
              )}
            />
            <select
              value={refreshInterval}
              onChange={(e) => setRefreshInterval(parseInt(e.target.value, 10) as RefreshInterval)}
              className={cn(
                "px-2 py-1.5 rounded-md border text-xs focus:outline-none focus:ring-2 focus:ring-amber-500/40",
                refreshInterval > 0
                  ? "bg-amber-900/30 border-amber-700 text-amber-300"
                  : "bg-slate-800/50 border-slate-700 text-slate-400"
              )}
            >
              {REFRESH_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Export */}
          <button
            onClick={handleExport}
            disabled={sortedRequests.length === 0}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm transition-colors"
          >
            <Download className="w-4 h-4" />
            Export
          </button>

          {/* Refresh indicator */}
          {isRefreshing && (
            <div className="flex items-center gap-2 text-xs text-amber-400">
              <div className="w-3 h-3 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
              Refreshing...
            </div>
          )}
        </div>

        {/* Active filters display */}
        {(clientFilter || searchQuery) && (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-slate-500">Showing {sortedRequests.length} of {requests.length}</span>
            {clientFilter && (
              <span className={cn(
                "flex items-center gap-1 px-2 py-1 rounded-full border",
                clientFilter === "<unknown>"
                  ? "bg-red-900/30 text-red-300 border-red-700"
                  : "bg-amber-900/30 text-amber-300 border-amber-700"
              )}>
                Client: {clientFilter === "<unknown>" ? "UNKNOWN" : clientFilter}
                <button onClick={() => setClientFilter(null)} className="hover:text-white">
                  <X className="h-3 w-3" />
                </button>
              </span>
            )}
          </div>
        )}
      </div>

      {/* Table */}
      <div
        ref={tableRef}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        className="max-h-[600px] overflow-auto focus:outline-none"
      >
        {/* Table Header */}
        <div className="sticky top-0 z-10 bg-slate-900/95 backdrop-blur-sm border-b border-slate-800">
          <div className="grid grid-cols-[120px_140px_1fr_200px_32px] gap-3 px-4 py-3 items-center">
            <SortableHeader label="Time" field="timestamp" currentField={sortField} direction={sortDirection} onSort={handleSort} />
            <SortableHeader label="Client" field="client_name" currentField={sortField} direction={sortDirection} onSort={handleSort} />
            <SortableHeader label="Endpoint" field="endpoint" currentField={sortField} direction={sortDirection} onSort={handleSort} />
            <SortableHeader label="Reason" field="block_reason" currentField={sortField} direction={sortDirection} onSort={handleSort} />
            <div />
          </div>
        </div>

        {/* Loading State */}
        {isLoading && (
          <div className="divide-y divide-slate-800/50">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="grid grid-cols-[120px_140px_1fr_200px_32px] gap-3 px-4 py-3 items-center">
                <div className="h-4 w-16 rounded bg-slate-800 animate-pulse" />
                <div className="h-4 w-24 rounded bg-slate-800 animate-pulse" />
                <div className="h-4 w-full max-w-xs rounded bg-slate-800 animate-pulse" />
                <div className="h-4 w-32 rounded bg-slate-800 animate-pulse" />
                <div className="h-4 w-4 rounded bg-slate-800 animate-pulse" />
              </div>
            ))}
          </div>
        )}

        {/* Empty State */}
        {!isLoading && sortedRequests.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="p-4 rounded-full bg-emerald-900/30 mb-4">
              <Shield className="w-10 h-10 text-emerald-400" />
            </div>
            <h3 className="text-lg font-semibold text-slate-100 mb-1">
              {requests.length === 0 ? "No blocked requests" : "No matching requests"}
            </h3>
            <p className="text-sm text-slate-500 max-w-sm">
              {requests.length === 0
                ? "All systems operational. Blocked requests will appear here when access is denied."
                : "Try adjusting your search or filter criteria"}
            </p>
          </div>
        )}

        {/* Table Rows */}
        {!isLoading && sortedRequests.length > 0 && (
          <div className="divide-y divide-slate-800/50">
            {sortedRequests.map((request, index) => {
              const isFocused = focusedRowIndex === index;
              const isExpanded = expandedIndex === index;

              return (
                <div key={index} className={cn(isExpanded && "bg-slate-800/30")}>
                  {/* Row */}
                  <button
                    onClick={() => handleToggleExpand(index)}
                    className={cn(
                      "w-full grid grid-cols-[120px_140px_1fr_200px_32px] gap-3 px-4 py-3 items-center text-left transition-colors",
                      "hover:bg-slate-800/30",
                      isFocused && "bg-amber-950/20 ring-1 ring-inset ring-amber-800",
                      isExpanded && "bg-amber-950/10"
                    )}
                  >
                    {/* Time */}
                    <div className="flex items-center gap-2">
                      <Clock className="w-3 h-3 text-slate-600" />
                      <span className="text-xs font-mono tabular-nums text-slate-400">
                        {formatRelativeTime(request.timestamp)}
                      </span>
                    </div>

                    {/* Client */}
                    <div>
                      <span
                        className={cn(
                          "text-xs font-medium px-2 py-0.5 rounded",
                          request.client_name === "<unknown>"
                            ? "bg-red-900/40 text-red-400 border border-red-700/50 animate-pulse"
                            : request.client_name
                              ? "bg-amber-900/30 text-amber-400 border border-amber-700/50"
                              : "text-slate-600"
                        )}
                      >
                        {request.client_name === "<unknown>" ? "UNKNOWN" : request.client_name || "—"}
                      </span>
                    </div>

                    {/* Endpoint */}
                    <div className="min-w-0">
                      <code className="text-xs font-mono text-slate-300 truncate block">
                        {request.endpoint}
                      </code>
                    </div>

                    {/* Reason */}
                    <div className="min-w-0">
                      <span className="text-xs text-red-400 truncate block">{request.block_reason}</span>
                    </div>

                    {/* Expand indicator */}
                    <div className="flex items-center justify-end">
                      <ChevronDown
                        className={cn(
                          "h-4 w-4 text-slate-600 transition-transform duration-200",
                          isExpanded && "rotate-180 text-amber-400"
                        )}
                      />
                    </div>
                  </button>

                  {/* Expanded Content */}
                  <div
                    className={cn(
                      "grid transition-all duration-300 ease-out",
                      isExpanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
                    )}
                  >
                    <div className="overflow-hidden">
                      <div className="border-t border-slate-800 bg-slate-900/50">
                        <ExpandedRowContent request={request} />
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer Stats */}
      {!isLoading && requests.length > 0 && (
        <div className="px-4 py-2 border-t border-slate-800 flex items-center justify-between text-xs text-slate-500">
          <span>
            {sortedRequests.length} of {requests.length} requests
          </span>
          <div className="flex items-center gap-1">
            <span className="px-1.5 py-0.5 rounded bg-slate-800 font-mono">j/k</span>
            <span>navigate</span>
            <span className="px-1.5 py-0.5 rounded bg-slate-800 font-mono ml-2">Enter</span>
            <span>expand</span>
          </div>
        </div>
      )}
    </div>
  );
}
