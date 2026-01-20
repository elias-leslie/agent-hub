"use client";

import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import {
  Shield,
  Users,
  Target,
  AlertTriangle,
  Clock,
  RefreshCw,
  Power,
  PowerOff,
  Search,
  X,
  ChevronDown,
  Download,
  Filter,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Copy,
  Check,
  Radio,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

interface ClientControl {
  client_name: string;
  enabled: boolean;
  disabled_at: string | null;
  disabled_by: string | null;
  reason: string | null;
  created_at: string;
  updated_at: string;
}

interface PurposeControl {
  purpose: string;
  enabled: boolean;
  disabled_at: string | null;
  disabled_by: string | null;
  reason: string | null;
  created_at: string;
  updated_at: string;
}

interface BlockedRequest {
  timestamp: string;
  client_name: string | null;
  purpose: string | null;
  source_path: string | null;
  block_reason: string;
  endpoint: string;
}

type SortField = "timestamp" | "client_name" | "purpose" | "endpoint" | "block_reason";
type SortDirection = "asc" | "desc";

// ─────────────────────────────────────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────────────────────────────────────

const REFRESH_OPTIONS = [
  { value: 0, label: "Manual" },
  { value: 5000, label: "5s" },
  { value: 15000, label: "15s" },
  { value: 30000, label: "30s" },
] as const;

type RefreshInterval = (typeof REFRESH_OPTIONS)[number]["value"];

// ─────────────────────────────────────────────────────────────────────────────
// API FUNCTIONS
// ─────────────────────────────────────────────────────────────────────────────

async function fetchClients(): Promise<ClientControl[]> {
  const res = await fetch("/api/admin/clients");
  const data = await res.json();
  return data.clients || [];
}

async function fetchPurposes(): Promise<PurposeControl[]> {
  const res = await fetch("/api/admin/purposes");
  const data = await res.json();
  return data.purposes || [];
}

async function fetchBlockedRequests(): Promise<BlockedRequest[]> {
  const res = await fetch("/api/admin/blocked-requests?limit=1000");
  const data = await res.json();
  return data.requests || [];
}

async function disableClient(clientName: string, reason: string, disabledBy: string): Promise<void> {
  await fetch(`/api/admin/clients/${clientName}/disable`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason, disabled_by: disabledBy }),
  });
}

async function enableClient(clientName: string): Promise<void> {
  await fetch(`/api/admin/clients/${clientName}/disable`, { method: "DELETE" });
}

async function disablePurpose(purpose: string, reason: string, disabledBy: string): Promise<void> {
  await fetch(`/api/admin/purposes/${purpose}/disable`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason, disabled_by: disabledBy }),
  });
}

async function enablePurpose(purpose: string): Promise<void> {
  await fetch(`/api/admin/purposes/${purpose}/disable`, { method: "DELETE" });
}

// ─────────────────────────────────────────────────────────────────────────────
// UTILITIES
// ─────────────────────────────────────────────────────────────────────────────

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffSecs < 10) return "just now";
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function downloadJson(data: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ─────────────────────────────────────────────────────────────────────────────
// HOLD TO CONFIRM HOOK
// ─────────────────────────────────────────────────────────────────────────────

function useHoldToConfirm(onConfirm: () => void, holdDuration: number = 1000) {
  const [isHolding, setIsHolding] = useState(false);
  const [progress, setProgress] = useState(0);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const startTimeRef = useRef<number>(0);

  const start = useCallback(() => {
    setIsHolding(true);
    startTimeRef.current = Date.now();
    intervalRef.current = setInterval(() => {
      const elapsed = Date.now() - startTimeRef.current;
      const newProgress = Math.min((elapsed / holdDuration) * 100, 100);
      setProgress(newProgress);
      if (newProgress >= 100) {
        if (intervalRef.current) clearInterval(intervalRef.current);
        onConfirm();
        setIsHolding(false);
        setProgress(0);
      }
    }, 16);
  }, [holdDuration, onConfirm]);

  const cancel = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    setIsHolding(false);
    setProgress(0);
  }, []);

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  return { isHolding, progress, start, cancel };
}

// ─────────────────────────────────────────────────────────────────────────────
// COPY BUTTON
// ─────────────────────────────────────────────────────────────────────────────

function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className={cn(
        "p-1 rounded transition-colors",
        "hover:bg-slate-700 text-slate-500 hover:text-slate-300",
        className
      )}
    >
      {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SORTABLE HEADER
// ─────────────────────────────────────────────────────────────────────────────

function SortableHeader({
  label,
  field,
  currentField,
  direction,
  onSort,
  align = "left",
}: {
  label: string;
  field: SortField;
  currentField: SortField;
  direction: SortDirection;
  onSort: (field: SortField) => void;
  align?: "left" | "right";
}) {
  const isActive = currentField === field;
  return (
    <button
      onClick={() => onSort(field)}
      className={cn(
        "flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest transition-colors",
        isActive ? "text-amber-400" : "text-slate-500 hover:text-slate-300",
        align === "right" && "justify-end"
      )}
    >
      {label}
      {isActive ? (
        direction === "asc" ? (
          <ArrowUp className="w-3 h-3" />
        ) : (
          <ArrowDown className="w-3 h-3" />
        )
      ) : (
        <ArrowUpDown className="w-3 h-3 opacity-40" />
      )}
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// KILL SWITCH TOGGLE
// ─────────────────────────────────────────────────────────────────────────────

function KillSwitchToggle({
  name,
  enabled,
  disabledAt,
  disabledBy,
  reason,
  onToggle,
  type,
}: {
  name: string;
  enabled: boolean;
  disabledAt: string | null;
  disabledBy: string | null;
  reason: string | null;
  onToggle: (reason: string) => void;
  type: "client" | "purpose";
}) {
  const [auditNote, setAuditNote] = useState("");
  const [showInput, setShowInput] = useState(false);

  const { isHolding, progress, start, cancel } = useHoldToConfirm(() => {
    if (!enabled || auditNote.trim()) {
      onToggle(auditNote);
      setAuditNote("");
      setShowInput(false);
    }
  });

  const handleClick = () => {
    if (enabled) {
      setShowInput(true);
    } else {
      start();
    }
  };

  return (
    <div
      className={cn(
        "group relative p-4 rounded-xl border transition-all duration-200",
        enabled
          ? "bg-slate-900/30 border-slate-800 hover:border-slate-700"
          : "bg-red-950/30 border-red-900/50 hover:border-red-800"
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "p-2 rounded-lg",
              enabled ? "bg-emerald-900/30 text-emerald-400" : "bg-red-900/30 text-red-400"
            )}
          >
            {type === "client" ? <Users className="w-4 h-4" /> : <Target className="w-4 h-4" />}
          </div>
          <div>
            <h3 className="font-medium text-slate-100">{name}</h3>
            {!enabled && disabledAt && (
              <p className="text-xs text-slate-500">
                Disabled {new Date(disabledAt).toLocaleDateString()}
                {disabledBy && ` by ${disabledBy}`}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {!enabled && reason && (
            <span className="text-xs text-red-400 max-w-[200px] truncate">{reason}</span>
          )}

          <button
            onClick={handleClick}
            onMouseDown={!enabled ? start : undefined}
            onMouseUp={!enabled ? cancel : undefined}
            onMouseLeave={!enabled ? cancel : undefined}
            className={cn(
              "relative overflow-hidden px-4 py-2 rounded-lg font-medium text-sm transition-all",
              enabled
                ? "bg-red-600/20 text-red-400 hover:bg-red-600/30"
                : "bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600/30"
            )}
          >
            {isHolding && (
              <div className="absolute inset-0 bg-current opacity-20" style={{ width: `${progress}%` }} />
            )}
            <span className="relative flex items-center gap-2">
              {enabled ? (
                <>
                  <PowerOff className="w-4 h-4" />
                  Disable
                </>
              ) : (
                <>
                  <Power className="w-4 h-4" />
                  Hold to Enable
                </>
              )}
            </span>
          </button>
        </div>
      </div>

      {showInput && enabled && (
        <div className="mt-4 pt-4 border-t border-slate-800">
          <label className="block text-sm text-slate-400 mb-2">Audit note (required)</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={auditNote}
              onChange={(e) => setAuditNote(e.target.value)}
              placeholder="Reason for disabling..."
              className="flex-1 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-red-500/50"
            />
            <button
              disabled={!auditNote.trim()}
              onMouseDown={auditNote.trim() ? start : undefined}
              onMouseUp={cancel}
              onMouseLeave={cancel}
              className={cn(
                "relative overflow-hidden px-4 py-2 rounded-lg font-medium text-sm transition-all",
                auditNote.trim()
                  ? "bg-red-600 text-white hover:bg-red-500"
                  : "bg-slate-700 text-slate-500 cursor-not-allowed"
              )}
            >
              {isHolding && (
                <div className="absolute inset-0 bg-white opacity-20" style={{ width: `${progress}%` }} />
              )}
              <span className="relative">Hold to Confirm</span>
            </button>
            <button
              onClick={() => {
                setShowInput(false);
                setAuditNote("");
              }}
              className="px-3 py-2 rounded-lg bg-slate-800 text-slate-400 hover:bg-slate-700"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// EXPANDED ROW CONTENT
// ─────────────────────────────────────────────────────────────────────────────

function ExpandedRowContent({ request }: { request: BlockedRequest }) {
  return (
    <div className="p-4 grid grid-cols-1 md:grid-cols-3 gap-4">
      {/* Main Details */}
      <div className="md:col-span-2 space-y-3">
        <div>
          <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-1">
            Block Reason
          </h4>
          <p className="text-sm text-red-400 font-mono bg-red-950/30 px-3 py-2 rounded-lg border border-red-900/50">
            {request.block_reason}
          </p>
        </div>

        <div>
          <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-1">
            Endpoint
          </h4>
          <div className="flex items-center gap-2">
            <code className="text-sm text-slate-300 font-mono bg-slate-800/50 px-3 py-2 rounded-lg flex-1">
              {request.endpoint}
            </code>
            <CopyButton text={request.endpoint} />
          </div>
        </div>

        {request.source_path && (
          <div>
            <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-1">
              Source Path
            </h4>
            <div className="flex items-center gap-2">
              <code className="text-sm text-slate-400 font-mono bg-slate-800/50 px-3 py-2 rounded-lg flex-1 truncate">
                {request.source_path}
              </code>
              <CopyButton text={request.source_path} />
            </div>
          </div>
        )}
      </div>

      {/* Metadata */}
      <div className="space-y-3">
        <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-500 border-b border-slate-800 pb-2">
          Request Info
        </h4>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between items-center">
            <span className="text-slate-500">Client</span>
            <span className={cn(
              "font-mono",
              request.client_name === "<unknown>" ? "text-red-400 font-bold" : "text-amber-400"
            )}>
              {request.client_name === "<unknown>" ? "UNKNOWN" : request.client_name || "—"}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-slate-500">Purpose</span>
            <span className="font-mono text-slate-300">{request.purpose || "—"}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-slate-500">Time</span>
            <span className="font-mono text-slate-400 tabular-nums">
              {new Date(request.timestamp).toLocaleString()}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// BLOCKED REQUESTS TABLE
// ─────────────────────────────────────────────────────────────────────────────

function BlockedRequestsTable({
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
          r.purpose?.toLowerCase().includes(q) ||
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
        case "purpose":
          cmp = (a.purpose || "").localeCompare(b.purpose || "");
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
          <div className="grid grid-cols-[120px_140px_100px_1fr_200px_32px] gap-3 px-4 py-3 items-center">
            <SortableHeader label="Time" field="timestamp" currentField={sortField} direction={sortDirection} onSort={handleSort} />
            <SortableHeader label="Client" field="client_name" currentField={sortField} direction={sortDirection} onSort={handleSort} />
            <SortableHeader label="Purpose" field="purpose" currentField={sortField} direction={sortDirection} onSort={handleSort} />
            <SortableHeader label="Endpoint" field="endpoint" currentField={sortField} direction={sortDirection} onSort={handleSort} />
            <SortableHeader label="Reason" field="block_reason" currentField={sortField} direction={sortDirection} onSort={handleSort} />
            <div />
          </div>
        </div>

        {/* Loading State */}
        {isLoading && (
          <div className="divide-y divide-slate-800/50">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="grid grid-cols-[120px_140px_100px_1fr_200px_32px] gap-3 px-4 py-3 items-center">
                <div className="h-4 w-16 rounded bg-slate-800 animate-pulse" />
                <div className="h-4 w-24 rounded bg-slate-800 animate-pulse" />
                <div className="h-4 w-16 rounded bg-slate-800 animate-pulse" />
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
                      "w-full grid grid-cols-[120px_140px_100px_1fr_200px_32px] gap-3 px-4 py-3 items-center text-left transition-colors",
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

                    {/* Purpose */}
                    <div>
                      <span className="text-xs text-slate-500">{request.purpose || "—"}</span>
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

// ─────────────────────────────────────────────────────────────────────────────
// MAIN PAGE
// ─────────────────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const [clients, setClients] = useState<ClientControl[]>([]);
  const [purposes, setPurposes] = useState<PurposeControl[]>([]);
  const [blockedRequests, setBlockedRequests] = useState<BlockedRequest[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const [c, p, b] = await Promise.all([fetchClients(), fetchPurposes(), fetchBlockedRequests()]);
      setClients(c);
      setPurposes(p);
      setBlockedRequests(b);
    } catch (error) {
      console.error("Failed to refresh:", error);
    } finally {
      setIsRefreshing(false);
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, [refresh]);

  const handleToggleClient = useCallback(
    async (clientName: string, enabled: boolean, reason: string) => {
      try {
        if (enabled) {
          await disableClient(clientName, reason, "admin");
        } else {
          await enableClient(clientName);
        }
        await refresh();
      } catch (error) {
        console.error("Failed to toggle client:", error);
      }
    },
    [refresh]
  );

  const handleTogglePurpose = useCallback(
    async (purpose: string, enabled: boolean, reason: string) => {
      try {
        if (enabled) {
          await disablePurpose(purpose, reason, "admin");
        } else {
          await enablePurpose(purpose);
        }
        await refresh();
      } catch (error) {
        console.error("Failed to toggle purpose:", error);
      }
    },
    [refresh]
  );

  // Stats calculations
  const todayBlocked = useMemo(() => {
    const today = new Date().toDateString();
    return blockedRequests.filter((r) => new Date(r.timestamp).toDateString() === today).length;
  }, [blockedRequests]);

  const unknownAttempts = useMemo(() => {
    return blockedRequests.filter((r) => r.client_name === "<unknown>").length;
  }, [blockedRequests]);

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Subtle grid pattern overlay */}
      <div
        className="fixed inset-0 pointer-events-none opacity-[0.015]"
        style={{
          backgroundImage: `linear-gradient(rgba(251,191,36,0.5) 1px, transparent 1px),
                            linear-gradient(90deg, rgba(251,191,36,0.5) 1px, transparent 1px)`,
          backgroundSize: "64px 64px",
        }}
      />

      {/* Header */}
      <header className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-4">
              <div className="p-2.5 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-600/20 border border-amber-500/30">
                <Shield className="w-6 h-6 text-amber-400" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-slate-100 tracking-tight">Usage Control</h1>
                <p className="text-xs text-slate-500">Kill switch administration</p>
              </div>
            </div>

            <div className="flex items-center gap-4">
              {/* Live indicator */}
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-950/50 border border-emerald-800/50">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                </span>
                <span className="text-xs font-medium text-emerald-400">Live</span>
              </div>

              <button
                onClick={refresh}
                disabled={isRefreshing}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors border border-slate-700"
              >
                <RefreshCw className={cn("w-4 h-4", isRefreshing && "animate-spin")} />
                Refresh
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-8 space-y-8 relative">
        {/* Stats Summary */}
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <div className="p-5 rounded-xl bg-gradient-to-br from-slate-900/80 to-slate-900/40 border border-slate-800 hover:border-slate-700 transition-colors">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 rounded-lg bg-emerald-900/30">
                <Users className="w-4 h-4 text-emerald-400" />
              </div>
              <span className="text-sm text-slate-400">Total Clients</span>
            </div>
            <div className="text-3xl font-bold text-slate-100 tabular-nums">{clients.length}</div>
          </div>

          <div className="p-5 rounded-xl bg-gradient-to-br from-slate-900/80 to-slate-900/40 border border-slate-800 hover:border-slate-700 transition-colors">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 rounded-lg bg-red-900/30">
                <PowerOff className="w-4 h-4 text-red-400" />
              </div>
              <span className="text-sm text-slate-400">Disabled Clients</span>
            </div>
            <div className="text-3xl font-bold text-red-400 tabular-nums">
              {clients.filter((c) => !c.enabled).length}
            </div>
          </div>

          <div className="p-5 rounded-xl bg-gradient-to-br from-slate-900/80 to-slate-900/40 border border-slate-800 hover:border-slate-700 transition-colors">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 rounded-lg bg-blue-900/30">
                <Target className="w-4 h-4 text-blue-400" />
              </div>
              <span className="text-sm text-slate-400">Total Purposes</span>
            </div>
            <div className="text-3xl font-bold text-slate-100 tabular-nums">{purposes.length}</div>
          </div>

          <div className="p-5 rounded-xl bg-gradient-to-br from-amber-950/50 to-slate-900/40 border border-amber-800/50 hover:border-amber-700 transition-colors">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 rounded-lg bg-amber-900/30">
                <Zap className="w-4 h-4 text-amber-400" />
              </div>
              <span className="text-sm text-amber-400/80">Blocked Today</span>
            </div>
            <div className="text-3xl font-bold text-amber-400 tabular-nums">{todayBlocked}</div>
          </div>

          <div className={cn(
            "p-5 rounded-xl border transition-colors",
            unknownAttempts > 0
              ? "bg-gradient-to-br from-red-950/50 to-slate-900/40 border-red-800/50 hover:border-red-700"
              : "bg-gradient-to-br from-slate-900/80 to-slate-900/40 border-slate-800 hover:border-slate-700"
          )}>
            <div className="flex items-center gap-3 mb-3">
              <div className={cn(
                "p-2 rounded-lg",
                unknownAttempts > 0 ? "bg-red-900/30" : "bg-slate-800"
              )}>
                <AlertTriangle className={cn(
                  "w-4 h-4",
                  unknownAttempts > 0 ? "text-red-400" : "text-slate-500"
                )} />
              </div>
              <span className={cn(
                "text-sm",
                unknownAttempts > 0 ? "text-red-400/80" : "text-slate-400"
              )}>Unknown Clients</span>
            </div>
            <div className={cn(
              "text-3xl font-bold tabular-nums",
              unknownAttempts > 0 ? "text-red-400" : "text-slate-500"
            )}>{unknownAttempts}</div>
          </div>
        </div>

        {/* Two-column layout for controls */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Clients Section */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <Users className="w-5 h-5 text-emerald-400" />
              <h2 className="text-lg font-semibold text-slate-100">Client Kill Switches</h2>
              <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
                {clients.length} registered
              </span>
            </div>
            <div className="space-y-3">
              {isLoading ? (
                <div className="animate-pulse space-y-3">
                  {[...Array(3)].map((_, i) => (
                    <div key={i} className="h-16 bg-slate-800/50 rounded-xl" />
                  ))}
                </div>
              ) : clients.length === 0 ? (
                <div className="text-center py-12 rounded-xl border border-dashed border-slate-800">
                  <Users className="w-8 h-8 text-slate-700 mx-auto mb-2" />
                  <p className="text-slate-500">No clients registered yet</p>
                  <p className="text-xs text-slate-600 mt-1">Clients auto-register on first API call</p>
                </div>
              ) : (
                clients.map((client) => (
                  <KillSwitchToggle
                    key={client.client_name}
                    name={client.client_name}
                    enabled={client.enabled}
                    disabledAt={client.disabled_at}
                    disabledBy={client.disabled_by}
                    reason={client.reason}
                    onToggle={(reason) => handleToggleClient(client.client_name, client.enabled, reason)}
                    type="client"
                  />
                ))
              )}
            </div>
          </section>

          {/* Purposes Section */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <Target className="w-5 h-5 text-blue-400" />
              <h2 className="text-lg font-semibold text-slate-100">Purpose Kill Switches</h2>
              <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
                {purposes.length} registered
              </span>
            </div>
            <div className="space-y-3">
              {isLoading ? (
                <div className="animate-pulse space-y-3">
                  {[...Array(3)].map((_, i) => (
                    <div key={i} className="h-16 bg-slate-800/50 rounded-xl" />
                  ))}
                </div>
              ) : purposes.length === 0 ? (
                <div className="text-center py-12 rounded-xl border border-dashed border-slate-800">
                  <Target className="w-8 h-8 text-slate-700 mx-auto mb-2" />
                  <p className="text-slate-500">No purposes registered yet</p>
                  <p className="text-xs text-slate-600 mt-1">Purposes are tracked via X-Purpose header</p>
                </div>
              ) : (
                purposes.map((purpose) => (
                  <KillSwitchToggle
                    key={purpose.purpose}
                    name={purpose.purpose}
                    enabled={purpose.enabled}
                    disabledAt={purpose.disabled_at}
                    disabledBy={purpose.disabled_by}
                    reason={purpose.reason}
                    onToggle={(reason) => handleTogglePurpose(purpose.purpose, purpose.enabled, reason)}
                    type="purpose"
                  />
                ))
              )}
            </div>
          </section>
        </div>

        {/* Blocked Requests Section - Full Width */}
        <section>
          <div className="flex items-center gap-3 mb-4">
            <AlertTriangle className="w-5 h-5 text-amber-400" />
            <h2 className="text-lg font-semibold text-slate-100">Blocked Requests</h2>
            <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
              {blockedRequests.length} total
            </span>
          </div>
          <BlockedRequestsTable
            requests={blockedRequests}
            isLoading={isLoading}
            onRefresh={refresh}
            isRefreshing={isRefreshing}
          />
        </section>
      </main>
    </div>
  );
}
