"use client";

import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { useQuery, useQueryClient, useInfiniteQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  Search,
  AlertCircle,
  RefreshCw,
  Gauge,
  Copy,
  Check,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  MessageSquare,
  Maximize2,
  Minimize2,
  Zap,
  TrendingUp,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchSessions,
  fetchSession,
  type SessionListItem,
  type Session,
} from "@/lib/api";
import { useSessionEvents } from "@/hooks/use-session-events";
import { LiveBadge, EventStream } from "@/components/monitoring";

// ─────────────────────────────────────────────────────────────────────────────
// CONSTANTS & TYPES
// ─────────────────────────────────────────────────────────────────────────────

const REFRESH_OPTIONS = [
  { value: 0, label: "Manual" },
  { value: 5000, label: "5s" },
  { value: 15000, label: "15s" },
  { value: 30000, label: "30s" },
  { value: 60000, label: "60s" },
] as const;

type RefreshInterval = (typeof REFRESH_OPTIONS)[number]["value"];
type SortField = "project" | "model" | "status" | "tokens" | "cost" | "time";
type SortDirection = "asc" | "desc";

const REFRESH_STORAGE_KEY = "sessions-auto-refresh";
const SORT_STORAGE_KEY = "sessions-sort";

// Cost per 1M tokens (approximate, varies by model)
const COST_PER_1M_INPUT: Record<string, number> = {
  "claude-opus-4-5": 15.0,
  "claude-sonnet-4-5": 3.0,
  "claude-haiku-4-5": 0.8,
  "gemini-3-pro": 1.25,
  "gemini-3-flash": 0.075,
  default: 2.0,
};

const COST_PER_1M_OUTPUT: Record<string, number> = {
  "claude-opus-4-5": 75.0,
  "claude-sonnet-4-5": 15.0,
  "claude-haiku-4-5": 4.0,
  "gemini-3-pro": 5.0,
  "gemini-3-flash": 0.3,
  default: 8.0,
};

// ─────────────────────────────────────────────────────────────────────────────
// FORMATTERS
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

function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
  return tokens.toString();
}

function formatTokenPair(input: number, output: number): string {
  if (input === 0 && output === 0) return "—";
  return `${formatTokens(input)} / ${formatTokens(output)}`;
}

function estimateCost(model: string, inputTokens: number, outputTokens: number): number {
  // Normalize model name for lookup
  const normalizedModel = model.toLowerCase();
  let inputRate = COST_PER_1M_INPUT.default;
  let outputRate = COST_PER_1M_OUTPUT.default;

  for (const key of Object.keys(COST_PER_1M_INPUT)) {
    if (normalizedModel.includes(key)) {
      inputRate = COST_PER_1M_INPUT[key];
      outputRate = COST_PER_1M_OUTPUT[key];
      break;
    }
  }

  return (inputTokens * inputRate + outputTokens * outputRate) / 1_000_000;
}

function formatCost(cost: number): string {
  if (cost === 0) return "—";
  if (cost < 0.0001) return "<$0.0001";
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  if (cost < 1) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
}

function formatDuration(startDate: string, endDate: string): string {
  const start = new Date(startDate).getTime();
  const end = new Date(endDate).getTime();
  const diffMs = end - start;
  if (diffMs < 1000) return `${diffMs}ms`;
  if (diffMs < 60000) return `${(diffMs / 1000).toFixed(1)}s`;
  return `${Math.floor(diffMs / 60000)}m ${Math.floor((diffMs % 60000) / 1000)}s`;
}

// ─────────────────────────────────────────────────────────────────────────────
// TOOLTIP - Simple hover tooltip
// ─────────────────────────────────────────────────────────────────────────────

function Tooltip({
  children,
  content,
  position = "top"
}: {
  children: React.ReactNode;
  content: React.ReactNode;
  position?: "top" | "bottom";
}) {
  const [show, setShow] = useState(false);

  return (
    <div
      className="relative inline-flex"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <div
          className={cn(
            "absolute z-50 px-2 py-1 text-[10px] font-medium whitespace-nowrap rounded shadow-lg",
            "bg-slate-900 text-white dark:bg-white dark:text-slate-900",
            "animate-in fade-in-0 zoom-in-95 duration-150",
            position === "top" ? "bottom-full mb-1.5 left-1/2 -translate-x-1/2" : "top-full mt-1.5 left-1/2 -translate-x-1/2"
          )}
        >
          {content}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MODEL PILL - Refined with provider-specific styling + click-to-filter
// ─────────────────────────────────────────────────────────────────────────────

function ModelPill({
  model,
  provider,
  onClick,
  isActive,
}: {
  model: string;
  provider: string;
  onClick?: () => void;
  isActive?: boolean;
}) {
  const isClaude = provider === "claude";

  // Extract meaningful model name
  const shortName = model
    .replace("claude-", "")
    .replace("gemini-", "")
    .replace("-preview", "")
    .replace("-20250514", "")
    .replace("-image", "")
    .slice(0, 12);

  return (
    <span
      onClick={(e) => {
        if (onClick) {
          e.stopPropagation();
          onClick();
        }
      }}
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide border transition-all",
        onClick && "cursor-pointer hover:scale-105 active:scale-95",
        isActive && "ring-2 ring-offset-1 ring-offset-white dark:ring-offset-slate-900",
        isClaude
          ? cn(
              "border-purple-400/60 text-purple-600 dark:text-purple-400 bg-purple-50/80 dark:bg-purple-950/40",
              isActive && "ring-purple-400"
            )
          : cn(
              "border-emerald-400/60 text-emerald-600 dark:text-emerald-400 bg-emerald-50/80 dark:bg-emerald-950/40",
              isActive && "ring-emerald-400"
            )
      )}
      title={onClick ? "Click to filter by model" : undefined}
    >
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-full",
          isClaude ? "bg-purple-500" : "bg-emerald-500"
        )}
      />
      {shortName}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// STATUS INDICATOR - Clean, minimal with semantic colors
// ─────────────────────────────────────────────────────────────────────────────

function StatusCell({ status, isLive }: { status: string; isLive?: boolean }) {
  const config: Record<string, { dot: string; bg: string; label: string }> = {
    active: {
      dot: "bg-blue-500",
      bg: "bg-blue-500/10",
      label: "Active",
    },
    completed: {
      dot: "bg-slate-400 dark:bg-slate-500",
      bg: "",
      label: "Done",
    },
    error: {
      dot: "bg-red-500",
      bg: "bg-red-500/10",
      label: "Error",
    },
    failed: {
      dot: "bg-red-500",
      bg: "bg-red-500/10",
      label: "Failed",
    },
  };

  const { dot, bg, label } = config[status] || config.completed;
  const showPulse = status === "active" || isLive;

  return (
    <div className={cn("flex items-center gap-2 min-w-[70px]", bg && "px-2 py-1 -mx-2 -my-1 rounded")}>
      <span className="relative flex h-2 w-2">
        <span
          className={cn(
            "absolute inline-flex h-full w-full rounded-full",
            dot,
            showPulse && "animate-ping opacity-75"
          )}
        />
        <span className={cn("relative inline-flex rounded-full h-2 w-2", dot)} />
      </span>
      <span className="text-[11px] text-slate-500 dark:text-slate-400 font-medium">
        {label}
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SORTABLE HEADER - Refined typography
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
        "flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider transition-colors",
        "text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300",
        isActive && "text-slate-700 dark:text-slate-200",
        align === "right" && "justify-end"
      )}
    >
      {label}
      {isActive ? (
        direction === "asc" ? (
          <ArrowUp className="h-3 w-3" />
        ) : (
          <ArrowDown className="h-3 w-3" />
        )
      ) : (
        <ArrowUpDown className="h-3 w-3 opacity-30" />
      )}
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// COPY ID BUTTON - Minimal, hover-reveal
// ─────────────────────────────────────────────────────────────────────────────

function CopyIdButton({ id, className, asSpan }: { id: string; className?: string; asSpan?: boolean }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    await navigator.clipboard.writeText(id);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const commonProps = {
    onClick: handleCopy,
    className: cn(
      "relative p-1 rounded-md transition-all cursor-pointer",
      "hover:bg-slate-200 dark:hover:bg-slate-700",
      "active:scale-95",
      className
    ),
    title: copied ? undefined : "Copy session ID",
  };

  const content = (
    <>
      {copied ? (
        <Check className="h-3.5 w-3.5 text-emerald-500" />
      ) : (
        <Copy className="h-3.5 w-3.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300" />
      )}
      {/* Copied tooltip */}
      {copied && (
        <span className="absolute -top-7 left-1/2 -translate-x-1/2 px-2 py-0.5 text-[10px] font-medium rounded bg-emerald-600 text-white whitespace-nowrap animate-in fade-in-0 zoom-in-95 duration-150">
          Copied!
        </span>
      )}
    </>
  );

  // Use span when inside another interactive element (button/link)
  if (asSpan) {
    return (
      <span role="button" tabIndex={0} {...commonProps} onKeyDown={(e) => e.key === 'Enter' && handleCopy(e as unknown as React.MouseEvent)}>
        {content}
      </span>
    );
  }

  return <button {...commonProps}>{content}</button>;
}

// ─────────────────────────────────────────────────────────────────────────────
// COLLAPSIBLE MESSAGE - For system prompts collapsed by default
// ─────────────────────────────────────────────────────────────────────────────

function CollapsibleMessage({
  role,
  content,
  agentName,
  tokens,
  defaultCollapsed = false,
}: {
  role: string;
  content: string;
  agentName?: string | null;
  tokens?: number | null;
  defaultCollapsed?: boolean;
}) {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
  const isSystem = role === "system";
  const previewLength = 100;

  return (
    <div
      className={cn(
        "p-3 rounded-lg text-xs border-l-2 transition-all",
        role === "user"
          ? "bg-blue-50/80 dark:bg-blue-950/30 border-l-blue-400"
          : role === "assistant"
            ? "bg-slate-100/80 dark:bg-slate-800/50 border-l-slate-400"
            : "bg-amber-50/80 dark:bg-amber-950/30 border-l-amber-400"
      )}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className="font-bold capitalize text-slate-700 dark:text-slate-200 text-[11px]">
          {role}
        </span>
        {agentName && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-700 text-slate-500">
            {agentName}
          </span>
        )}
        {isSystem && (
          <button
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="text-[10px] px-1.5 py-0.5 rounded bg-amber-200 dark:bg-amber-800 text-amber-700 dark:text-amber-200 hover:bg-amber-300 dark:hover:bg-amber-700 transition-colors flex items-center gap-1"
          >
            {isCollapsed ? (
              <>
                <ChevronDown className="h-2.5 w-2.5" />
                Show
              </>
            ) : (
              <>
                <ChevronUp className="h-2.5 w-2.5" />
                Hide
              </>
            )}
          </button>
        )}
        {tokens && (
          <span className="text-[10px] text-slate-400 font-mono tabular-nums ml-auto">
            {formatTokens(tokens)}
          </span>
        )}
      </div>
      <div
        className={cn(
          "text-slate-600 dark:text-slate-300 whitespace-pre-wrap break-words leading-relaxed transition-all overflow-hidden",
          isCollapsed && "max-h-[3em]"
        )}
      >
        {isCollapsed ? (
          <span className="text-slate-400 italic">
            {content.slice(0, previewLength)}
            {content.length > previewLength && "..."}
          </span>
        ) : (
          content
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// EXPANDED ROW - Three-pane layout (Metrics | Transcript | Meta)
// ─────────────────────────────────────────────────────────────────────────────

function ExpandedRowContent({
  session,
  expandedData,
  isLoading,
}: {
  session: SessionListItem;
  expandedData: Session | null;
  isLoading: boolean;
}) {
  const [isWidthExpanded, setIsWidthExpanded] = useState(false);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-sm text-slate-400">
        <RefreshCw className="h-4 w-4 animate-spin mr-2" />
        Loading session details...
      </div>
    );
  }

  if (!expandedData) {
    return (
      <div className="flex items-center justify-center py-16 text-sm text-slate-400">
        Failed to load session details
      </div>
    );
  }

  const messageCount = expandedData.messages?.length || 0;
  const cost = estimateCost(
    session.model,
    expandedData.total_input_tokens || 0,
    expandedData.total_output_tokens || 0
  );

  return (
    <div className="relative overflow-y-auto min-h-[280px] max-h-[60vh]">
      <div
        className={cn(
          "grid gap-6 p-5 transition-all duration-300",
          isWidthExpanded ? "grid-cols-1" : "grid-cols-[200px_1fr_220px]"
        )}
      >
        {/* METRICS PANE - Left sidebar */}
        {!isWidthExpanded && (
          <div className="space-y-4">
            <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-400 border-b border-slate-200 dark:border-slate-700 pb-2">
              Metrics
            </h4>

            {/* Context Usage */}
            {expandedData.context_usage && (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="flex items-center gap-1.5 text-slate-500">
                    <Gauge className="h-3 w-3" /> Context
                  </span>
                  <span className="font-mono tabular-nums font-semibold text-slate-700 dark:text-slate-200">
                    {expandedData.context_usage.percent_used.toFixed(0)}%
                  </span>
                </div>
                <div className="h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      expandedData.context_usage.percent_used > 90
                        ? "bg-red-500"
                        : expandedData.context_usage.percent_used > 70
                          ? "bg-amber-500"
                          : "bg-emerald-500"
                    )}
                    style={{
                      width: `${Math.min(100, expandedData.context_usage.percent_used)}%`,
                    }}
                  />
                </div>
                <div className="flex justify-between text-[10px] text-slate-400 font-mono tabular-nums">
                  <span>{formatTokens(expandedData.context_usage.used_tokens)}</span>
                  <span>{formatTokens(expandedData.context_usage.limit_tokens)}</span>
                </div>
              </div>
            )}

            {/* Token Stats */}
            <div className="grid grid-cols-2 gap-2">
              <div className="p-2.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-100 dark:border-emerald-900/50">
                <p className="text-[9px] text-emerald-600 dark:text-emerald-400 uppercase tracking-wide font-semibold">
                  Input
                </p>
                <p className="text-sm font-bold font-mono tabular-nums text-emerald-700 dark:text-emerald-300">
                  {formatTokens(expandedData.total_input_tokens || 0)}
                </p>
              </div>
              <div className="p-2.5 rounded-lg bg-blue-50 dark:bg-blue-950/30 border border-blue-100 dark:border-blue-900/50">
                <p className="text-[9px] text-blue-600 dark:text-blue-400 uppercase tracking-wide font-semibold">
                  Output
                </p>
                <p className="text-sm font-bold font-mono tabular-nums text-blue-700 dark:text-blue-300">
                  {formatTokens(expandedData.total_output_tokens || 0)}
                </p>
              </div>
            </div>

            {/* Cost & Duration */}
            <div className="space-y-2 pt-2 border-t border-slate-200 dark:border-slate-700">
              <div className="flex justify-between text-[11px]">
                <span className="text-slate-500">Est. Cost</span>
                <span className="font-mono tabular-nums font-semibold text-amber-600 dark:text-amber-400">
                  {formatCost(cost)}
                </span>
              </div>
              <div className="flex justify-between text-[11px]">
                <span className="text-slate-500">Duration</span>
                <span className="font-mono tabular-nums text-slate-700 dark:text-slate-200">
                  {formatDuration(expandedData.created_at, expandedData.updated_at)}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* TRANSCRIPT PANE - Center, scrollable messages */}
        <div className={cn("flex flex-col min-w-0", !isWidthExpanded && "border-x border-slate-200 dark:border-slate-700 px-5")}>
          <div className="sticky top-0 z-10 flex items-center justify-between pb-3 bg-slate-50/95 dark:bg-slate-900/95 backdrop-blur-sm -mx-5 px-5 pt-1">
            <div className="flex items-center gap-2">
              <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-400">
                Messages
              </h4>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300 tabular-nums">
                {messageCount}
              </span>
            </div>
            <button
              onClick={() => setIsWidthExpanded(!isWidthExpanded)}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-semibold text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
            >
              {isWidthExpanded ? (
                <>
                  <Minimize2 className="h-3 w-3" />
                  <span className="hidden sm:inline">Collapse</span>
                </>
              ) : (
                <>
                  <Maximize2 className="h-3 w-3" />
                  <span className="hidden sm:inline">Expand</span>
                </>
              )}
            </button>
          </div>

          <div className="space-y-2 overflow-y-auto pr-2">
            {expandedData.messages && expandedData.messages.length > 0 ? (
              expandedData.messages.map((msg) => {
                const isSystem = msg.role === "system";
                return (
                  <CollapsibleMessage
                    key={msg.id}
                    role={msg.role}
                    content={msg.content}
                    agentName={msg.agent_name}
                    tokens={msg.tokens}
                    defaultCollapsed={isSystem}
                  />
                );
              })
            ) : (
              <p className="text-sm text-slate-400 text-center py-12">No messages</p>
            )}
          </div>
        </div>

        {/* META PANE - Right sidebar */}
        {!isWidthExpanded && (
          <div className="space-y-4">
            <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-400 border-b border-slate-200 dark:border-slate-700 pb-2">
              Session Info
            </h4>

            {/* Session ID */}
            <div>
              <p className="text-[9px] text-slate-400 uppercase tracking-wide font-semibold mb-1">
                Session ID
              </p>
              <div className="flex items-center gap-2">
                <code className="text-[10px] font-mono text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 px-2 py-1 rounded truncate flex-1">
                  {session.id}
                </code>
                <CopyIdButton id={session.id} />
              </div>
            </div>

            {/* Agent */}
            {expandedData.agent_slug && (
              <div>
                <p className="text-[9px] text-slate-400 uppercase tracking-wide font-semibold mb-1">
                  Agent
                </p>
                <p className="text-xs text-slate-700 dark:text-slate-200">
                  {expandedData.agent_slug}
                </p>
              </div>
            )}

            {/* Agent breakdown */}
            {expandedData.agent_token_breakdown && expandedData.agent_token_breakdown.length > 0 && (
              <div>
                <p className="text-[9px] text-slate-400 uppercase tracking-wide font-semibold mb-2">
                  Agents
                </p>
                <div className="space-y-1.5">
                  {expandedData.agent_token_breakdown.map((agent) => (
                    <div
                      key={agent.agent_id}
                      className="flex items-center justify-between text-[11px] p-2 rounded bg-slate-100 dark:bg-slate-800/50"
                    >
                      <span className="text-slate-600 dark:text-slate-300 truncate">
                        {agent.agent_name || agent.agent_id.slice(0, 8)}
                      </span>
                      <span className="font-mono tabular-nums text-slate-500 font-semibold">
                        {formatTokens(agent.total_tokens)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Timestamps */}
            <div className="text-[10px] text-slate-400 space-y-1.5 pt-2 border-t border-slate-200 dark:border-slate-700">
              <div className="flex justify-between">
                <span>Created</span>
                <span className="font-mono tabular-nums text-slate-600 dark:text-slate-300">
                  {new Date(expandedData.created_at).toLocaleTimeString()}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Updated</span>
                <span className="font-mono tabular-nums text-slate-600 dark:text-slate-300">
                  {new Date(expandedData.updated_at).toLocaleTimeString()}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN SESSIONS PAGE
// ─────────────────────────────────────────────────────────────────────────────

export default function SessionsPage() {
  const queryClient = useQueryClient();
  const tableRef = useRef<HTMLDivElement>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [projectFilter, setProjectFilter] = useState<string>("");
  const [modelFilter, setModelFilter] = useState<string>(""); // Model click filter
  const [searchQuery, setSearchQuery] = useState("");
  const [showLiveView, setShowLiveView] = useState(false);
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);
  const [expandedSessionData, setExpandedSessionData] = useState<Session | null>(null);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState<RefreshInterval>(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [sortField, setSortField] = useState<SortField>("time");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [focusedRowIndex, setFocusedRowIndex] = useState<number>(-1); // Keyboard nav
  const [flashingSessionIds, setFlashingSessionIds] = useState<Set<string>>(new Set()); // Flash animation
  const pageSize = 25;

  // Load preferences from localStorage
  useEffect(() => {
    const storedRefresh = localStorage.getItem(REFRESH_STORAGE_KEY);
    if (storedRefresh) {
      const parsed = parseInt(storedRefresh, 10);
      if (REFRESH_OPTIONS.some((opt) => opt.value === parsed)) {
        setRefreshInterval(parsed as RefreshInterval);
      }
    }

    const storedSort = localStorage.getItem(SORT_STORAGE_KEY);
    if (storedSort) {
      try {
        const { field, direction } = JSON.parse(storedSort);
        setSortField(field);
        setSortDirection(direction);
      } catch {
        // ignore
      }
    }
  }, []);

  const handleRefreshChange = useCallback((interval: RefreshInterval) => {
    setRefreshInterval(interval);
    localStorage.setItem(REFRESH_STORAGE_KEY, String(interval));
  }, []);

  const handleSort = useCallback(
    (field: SortField) => {
      const newDirection =
        sortField === field && sortDirection === "desc" ? "asc" : "desc";
      setSortField(field);
      setSortDirection(newDirection);
      localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify({ field, direction: newDirection }));
    },
    [sortField, sortDirection]
  );

  // Auto-refresh effect
  useEffect(() => {
    if (refreshInterval === 0) return;
    const intervalId = setInterval(() => {
      setIsRefreshing(true);
      queryClient.invalidateQueries({ queryKey: ["sessions"] }).finally(() => {
        setTimeout(() => setIsRefreshing(false), 500);
      });
    }, refreshInterval);
    return () => clearInterval(intervalId);
  }, [refreshInterval, queryClient]);

  // Fetch session details when expanded
  const handleToggleExpand = async (sessionId: string) => {
    if (expandedSessionId === sessionId) {
      setExpandedSessionId(null);
      setExpandedSessionData(null);
      return;
    }
    setExpandedSessionId(sessionId);
    setIsLoadingDetails(true);
    try {
      const data = await fetchSession(sessionId);
      setExpandedSessionData(data);
    } catch {
      setExpandedSessionData(null);
    } finally {
      setIsLoadingDetails(false);
    }
  };

  // Real-time events subscription
  const { events, status: wsStatus } = useSessionEvents({
    autoConnect: showLiveView,
    autoReconnect: showLiveView,
  });

  // Track live session IDs
  const liveSessionIds = useMemo(() => {
    const recentEvents = events.filter(
      (e) => new Date().getTime() - new Date(e.timestamp).getTime() < 60000
    );
    return new Set(recentEvents.map((e) => e.session_id));
  }, [events]);

  const {
    data,
    isLoading,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["sessions", { status: statusFilter, project: projectFilter, pageSize }],
    queryFn: ({ pageParam = 1 }) =>
      fetchSessions({
        page: pageParam,
        page_size: pageSize,
        status: statusFilter || undefined,
        project_id: projectFilter || undefined,
      }),
    getNextPageParam: (lastPage) => {
      const totalPages = Math.ceil(lastPage.total / lastPage.page_size);
      return lastPage.page < totalPages ? lastPage.page + 1 : undefined;
    },
    initialPageParam: 1,
  });

  // Flatten all pages into single array
  const allSessions = useMemo(() =>
    data?.pages.flatMap((page) => page.sessions) ?? [],
    [data]
  );
  const total = data?.pages[0]?.total ?? 0;

  // Scroll handler for infinite loading
  const handleScroll = useCallback(() => {
    if (!tableRef.current || isFetchingNextPage || !hasNextPage) return;
    const { scrollTop, scrollHeight, clientHeight } = tableRef.current;
    if (scrollHeight - scrollTop - clientHeight < 500) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Filter and sort sessions
  const sortedSessions = useMemo(() => {
    let sessions = allSessions;

    // Filter by model (click-to-filter)
    if (modelFilter) {
      sessions = sessions.filter((s) => s.model === modelFilter);
    }

    // Filter by search
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      sessions = sessions.filter(
        (s) =>
          s.id.toLowerCase().includes(query) ||
          s.project_id.toLowerCase().includes(query) ||
          s.model.toLowerCase().includes(query) ||
          s.agent_slug?.toLowerCase().includes(query)
      );
    }

    // Sort
    const sorted = [...sessions].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "project":
          cmp = a.project_id.localeCompare(b.project_id);
          break;
        case "model":
          cmp = a.model.localeCompare(b.model);
          break;
        case "status":
          cmp = a.status.localeCompare(b.status);
          break;
        case "tokens":
          cmp = (a.total_input_tokens + a.total_output_tokens) - (b.total_input_tokens + b.total_output_tokens);
          break;
        case "cost": {
          const costA = estimateCost(a.model, a.total_input_tokens, a.total_output_tokens);
          const costB = estimateCost(b.model, b.total_input_tokens, b.total_output_tokens);
          cmp = costA - costB;
          break;
        }
        case "time":
          cmp = new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime();
          break;
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });

    return sorted;
  }, [allSessions, modelFilter, searchQuery, sortField, sortDirection]);


  // Keyboard navigation handler
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!sortedSessions.length) return;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setFocusedRowIndex((prev) => Math.min(prev + 1, sortedSessions.length - 1));
          break;
        case "ArrowUp":
          e.preventDefault();
          setFocusedRowIndex((prev) => Math.max(prev - 1, 0));
          break;
        case "Enter":
        case " ":
          e.preventDefault();
          if (focusedRowIndex >= 0 && focusedRowIndex < sortedSessions.length) {
            handleToggleExpand(sortedSessions[focusedRowIndex].id);
          }
          break;
        case "Escape":
          e.preventDefault();
          setExpandedSessionId(null);
          setExpandedSessionData(null);
          break;
      }
    },
    [sortedSessions, focusedRowIndex]
  );

  // Calculate page stats
  const pageStats = useMemo(() => {
    if (!sortedSessions.length) return null;
    const totalTokens = sortedSessions.reduce(
      (sum, s) => sum + s.total_input_tokens + s.total_output_tokens,
      0
    );
    const totalCost = sortedSessions.reduce(
      (sum, s) => sum + estimateCost(s.model, s.total_input_tokens, s.total_output_tokens),
      0
    );
    return { totalTokens, totalCost };
  }, [sortedSessions]);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* HEADER */}
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
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8 pr-3 py-1.5 w-36 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500"
                />
              </div>

              {/* Status Filter */}
              <select
                data-testid="filter-status"
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                }}
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
                onChange={(e) => {
                  setProjectFilter(e.target.value);
                }}
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
                  onChange={(e) => handleRefreshChange(parseInt(e.target.value, 10) as RefreshInterval)}
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
                onClick={() => setShowLiveView(!showLiveView)}
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

      <main className="px-6 lg:px-8 py-5">
        {/* Live Events Panel */}
        {showLiveView && (
          <div className="mb-5 rounded-lg border border-green-200 dark:border-green-800 bg-white dark:bg-slate-900 overflow-hidden">
            <div className="px-4 py-2 bg-green-50 dark:bg-green-950/30 border-b border-green-200 dark:border-green-800 flex items-center gap-2">
              <LiveBadge size="sm" />
              <span className="text-xs font-semibold text-green-700 dark:text-green-300">
                Real-time Events
              </span>
              <span className="text-[10px] text-green-600 dark:text-green-400 ml-auto font-mono tabular-nums">
                {events.length}
              </span>
            </div>
            <EventStream events={events} maxHeight="200px" />
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="flex items-center gap-2 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 mb-5">
            <AlertCircle className="h-4 w-4" />
            <p className="text-xs font-medium">Failed to load sessions</p>
          </div>
        )}

        {/* Active model filter indicator */}
        {modelFilter && (
          <div className="mb-4 flex items-center gap-2">
            <span className="text-xs text-slate-500 dark:text-slate-400">Filtered by model:</span>
            <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
              {modelFilter}
              <button
                onClick={() => setModelFilter("")}
                className="ml-1 p-0.5 rounded-full hover:bg-purple-200 dark:hover:bg-purple-800 transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          </div>
        )}

        {/* Loading - Skeleton rows */}
        {isLoading && (
          <div className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
            {/* Skeleton header */}
            <div className="h-10 bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-700" />
            {/* Skeleton rows */}
            {Array.from({ length: 10 }).map((_, i) => (
              <div
                key={i}
                className="grid grid-cols-[80px_minmax(120px,1fr)_minmax(140px,1.5fr)_130px_100px_80px_70px_36px] gap-3 px-4 py-3 border-b border-slate-100 dark:border-slate-800/50"
              >
                <div className="h-4 w-16 rounded animate-shimmer" />
                <div className="h-4 w-24 rounded animate-shimmer" />
                <div className="h-4 w-32 rounded animate-shimmer" />
                <div className="h-5 w-20 rounded-full animate-shimmer" />
                <div className="h-4 w-16 rounded animate-shimmer ml-auto" />
                <div className="h-4 w-14 rounded animate-shimmer ml-auto" />
                <div className="h-4 w-12 rounded animate-shimmer ml-auto" />
                <div className="h-4 w-4 rounded animate-shimmer ml-auto" />
              </div>
            ))}
          </div>
        )}

        {/* SESSIONS TABLE */}
        {data && (
          <>
            {sortedSessions.length === 0 ? (
              <div className="text-center py-20 text-slate-400">
                <MessageSquare className="h-10 w-10 mx-auto mb-3 opacity-30" />
                <p className="text-sm font-medium">{modelFilter ? `No sessions with model: ${modelFilter}` : "No sessions found"}</p>
              </div>
            ) : (
              <div
                ref={tableRef}
                tabIndex={0}
                onKeyDown={handleKeyDown}
                onScroll={handleScroll}
                className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 overflow-auto shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 max-h-[calc(100vh-280px)]">
                {/* TABLE HEADER - Sticky */}
                <div className="sticky top-14 z-20 bg-slate-50/95 dark:bg-slate-800/95 backdrop-blur-sm border-b border-slate-200 dark:border-slate-700">
                  <div className="grid grid-cols-[80px_minmax(120px,1fr)_minmax(140px,1.5fr)_130px_100px_80px_70px_36px] gap-3 px-4 py-2.5 items-center">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Status
                    </span>
                    <SortableHeader
                      label="Project"
                      field="project"
                      currentField={sortField}
                      direction={sortDirection}
                      onSort={handleSort}
                    />
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Agent
                    </span>
                    <SortableHeader
                      label="Model"
                      field="model"
                      currentField={sortField}
                      direction={sortDirection}
                      onSort={handleSort}
                    />
                    <SortableHeader
                      label="Tokens"
                      field="tokens"
                      currentField={sortField}
                      direction={sortDirection}
                      onSort={handleSort}
                      align="right"
                    />
                    <SortableHeader
                      label="Cost"
                      field="cost"
                      currentField={sortField}
                      direction={sortDirection}
                      onSort={handleSort}
                      align="right"
                    />
                    <SortableHeader
                      label="Time"
                      field="time"
                      currentField={sortField}
                      direction={sortDirection}
                      onSort={handleSort}
                      align="right"
                    />
                    <div /> {/* Actions column */}
                  </div>
                </div>

                {/* TABLE BODY */}
                <div className="divide-y divide-slate-100 dark:divide-slate-800/50">
                  {sortedSessions.map((session, index) => {
                    const isExpanded = expandedSessionId === session.id;
                    const isLive = liveSessionIds.has(session.id);
                    const isFocused = focusedRowIndex === index;
                    const isFlashing = flashingSessionIds.has(session.id);
                    const cost = estimateCost(
                      session.model,
                      session.total_input_tokens,
                      session.total_output_tokens
                    );
                    // Cost breakdown for tooltip
                    const inputCost = (session.total_input_tokens * (COST_PER_1M_INPUT[session.model] || COST_PER_1M_INPUT.default)) / 1_000_000;
                    const outputCost = (session.total_output_tokens * (COST_PER_1M_OUTPUT[session.model] || COST_PER_1M_OUTPUT.default)) / 1_000_000;

                    return (
                      <div
                        key={session.id}
                        data-testid="session-row"
                        className={cn(
                          "transition-all duration-300",
                          isLive && "bg-emerald-50/50 dark:bg-emerald-950/10",
                          isFocused && "bg-blue-50 dark:bg-blue-950/20 ring-1 ring-inset ring-blue-200 dark:ring-blue-800",
                          isFlashing && "animate-flash"
                        )}
                      >
                        {/* ROW */}
                        <button
                          onClick={() => handleToggleExpand(session.id)}
                          className="w-full grid grid-cols-[80px_minmax(120px,1fr)_minmax(140px,1.5fr)_130px_100px_80px_70px_36px] gap-3 px-4 py-2.5 items-center text-left hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors group"
                        >
                          {/* Status */}
                          <StatusCell status={session.status} isLive={isLive} />

                          {/* Project */}
                          <div className="min-w-0">
                            <span className="text-xs font-semibold text-slate-800 dark:text-slate-100 truncate block">
                              {session.project_id}
                            </span>
                          </div>

                          {/* Agent */}
                          <div className="min-w-0">
                            <span className="text-xs text-slate-500 dark:text-slate-400 truncate block">
                              {session.agent_slug || "—"}
                            </span>
                          </div>

                          {/* Model - click to filter */}
                          <ModelPill
                            model={session.model}
                            provider={session.provider}
                            onClick={() => setModelFilter(modelFilter === session.model ? "" : session.model)}
                            isActive={modelFilter === session.model}
                          />

                          {/* Tokens (In / Out) with cost breakdown tooltip */}
                          <Tooltip
                            content={
                              <div className="space-y-0.5">
                                <div>Input: {formatTokens(session.total_input_tokens)} ({formatCost(inputCost)})</div>
                                <div>Output: {formatTokens(session.total_output_tokens)} ({formatCost(outputCost)})</div>
                              </div>
                            }
                            position="top"
                          >
                            <span className="text-[11px] font-mono tabular-nums text-slate-600 dark:text-slate-300 cursor-help">
                              {formatTokenPair(session.total_input_tokens, session.total_output_tokens)}
                            </span>
                          </Tooltip>

                          {/* Cost */}
                          <div className="text-right">
                            <span className={cn(
                              "text-[11px] font-mono tabular-nums font-medium",
                              cost > 0.01
                                ? "text-amber-600 dark:text-amber-400"
                                : "text-slate-500 dark:text-slate-400"
                            )}>
                              {formatCost(cost)}
                            </span>
                          </div>

                          {/* Time */}
                          <div className="text-right">
                            <span className="text-[11px] font-mono tabular-nums text-slate-500 dark:text-slate-400">
                              {formatRelativeTime(session.updated_at)}
                            </span>
                          </div>

                          {/* Actions */}
                          <div className="flex items-center justify-end gap-0.5">
                            <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                              <CopyIdButton id={session.id} asSpan />
                            </div>
                            <ChevronDown
                              className={cn(
                                "h-4 w-4 text-slate-400 transition-transform duration-200",
                                isExpanded && "rotate-180"
                              )}
                            />
                          </div>
                        </button>

                        {/* EXPANDED CONTENT - Accordion push animation */}
                        <div
                          className={cn(
                            "grid transition-all duration-300 ease-out",
                            isExpanded
                              ? "grid-rows-[1fr] opacity-100"
                              : "grid-rows-[0fr] opacity-0"
                          )}
                        >
                          <div className="overflow-hidden">
                            <div className="border-t border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/80">
                              <ExpandedRowContent
                                session={session}
                                expandedData={isExpanded ? expandedSessionData : null}
                                isLoading={isExpanded && isLoadingDetails}
                              />
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Infinite scroll loading indicator */}
            {isFetchingNextPage && (
              <div className="flex items-center justify-center py-4 mt-3">
                <div className="flex items-center gap-2 text-slate-400 text-sm">
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Loading more sessions...
                </div>
              </div>
            )}

            {/* End of list indicator */}
            {!hasNextPage && allSessions.length > 0 && !isFetchingNextPage && (
              <div className="flex items-center justify-center py-3 mt-3 text-xs text-slate-500 bg-slate-50 dark:bg-slate-900/50 rounded-lg">
                Showing all {allSessions.length} of {total} sessions
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
