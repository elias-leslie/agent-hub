"use client";

import { Suspense, useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  Brain,
  Search,
  X,
  ChevronDown,
  RefreshCw,
  Copy,
  Check,
  Trash2,
  Download,
  AlertTriangle,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Eye,
  MessageCircle,
  ThumbsUp,
  Database,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useMemory } from "@/hooks/use-memory";
import type {
  MemoryCategory,
  MemoryScope,
  MemorySortBy,
  MemoryEpisode,
} from "@/lib/memory-api";

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
type SortField = "scope" | "category" | "content" | "created_at" | "utility";
type SortDirection = "asc" | "desc";

const REFRESH_STORAGE_KEY = "memory-auto-refresh";
const SORT_STORAGE_KEY = "memory-sort";

const CATEGORY_CONFIG: Record<
  MemoryCategory,
  { icon: string; label: string; color: string; bg: string }
> = {
  coding_standard: {
    icon: "📏",
    label: "Standard",
    color: "text-blue-600 dark:text-blue-400",
    bg: "bg-blue-500/10 border-blue-400/40",
  },
  troubleshooting_guide: {
    icon: "⚠️",
    label: "Gotcha",
    color: "text-amber-600 dark:text-amber-400",
    bg: "bg-amber-500/10 border-amber-400/40",
  },
  system_design: {
    icon: "🏗️",
    label: "Design",
    color: "text-purple-600 dark:text-purple-400",
    bg: "bg-purple-500/10 border-purple-400/40",
  },
  operational_context: {
    icon: "⚙️",
    label: "Ops",
    color: "text-slate-600 dark:text-slate-400",
    bg: "bg-slate-500/10 border-slate-400/40",
  },
  domain_knowledge: {
    icon: "📚",
    label: "Domain",
    color: "text-emerald-600 dark:text-emerald-400",
    bg: "bg-emerald-500/10 border-emerald-400/40",
  },
  active_state: {
    icon: "▶️",
    label: "Active",
    color: "text-cyan-600 dark:text-cyan-400",
    bg: "bg-cyan-500/10 border-cyan-400/40",
  },
};

const SCOPE_CONFIG: Record<MemoryScope, { label: string; color: string; bg: string }> = {
  global: {
    label: "Global",
    color: "text-indigo-600 dark:text-indigo-400",
    bg: "bg-indigo-500/10 border-indigo-400/40",
  },
  project: {
    label: "Project",
    color: "text-teal-600 dark:text-teal-400",
    bg: "bg-teal-500/10 border-teal-400/40",
  },
  task: {
    label: "Task",
    color: "text-orange-600 dark:text-orange-400",
    bg: "bg-orange-500/10 border-orange-400/40",
  },
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
  if (diffSecs < 60) return `${diffSecs}s`;
  if (diffMins < 60) return `${diffMins}m`;
  if (diffHours < 24) return `${diffHours}h`;
  if (diffDays < 7) return `${diffDays}d`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ─────────────────────────────────────────────────────────────────────────────
// TOOLTIP
// ─────────────────────────────────────────────────────────────────────────────

function Tooltip({
  children,
  content,
  position = "top",
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
            position === "top"
              ? "bottom-full mb-1.5 left-1/2 -translate-x-1/2"
              : "top-full mt-1.5 left-1/2 -translate-x-1/2"
          )}
        >
          {content}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// COPY BUTTON
// ─────────────────────────────────────────────────────────────────────────────

function CopyButton({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className={cn(
        "relative p-1 rounded-md transition-all cursor-pointer",
        "hover:bg-slate-200 dark:hover:bg-slate-700",
        "active:scale-95",
        className
      )}
      title={copied ? undefined : "Copy to clipboard"}
    >
      {copied ? (
        <Check className="h-3 w-3 text-emerald-500" />
      ) : (
        <Copy className="h-3 w-3 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300" />
      )}
      {copied && (
        <span className="absolute -top-7 left-1/2 -translate-x-1/2 px-2 py-0.5 text-[10px] font-medium rounded bg-emerald-600 text-white whitespace-nowrap animate-in fade-in-0 zoom-in-95 duration-150">
          Copied!
        </span>
      )}
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
// SCOPE & CATEGORY PILLS
// ─────────────────────────────────────────────────────────────────────────────

function ScopePill({
  scope,
  onClick,
  isActive,
  size = "sm",
}: {
  scope: MemoryScope;
  onClick?: () => void;
  isActive?: boolean;
  size?: "sm" | "md";
}) {
  const config = SCOPE_CONFIG[scope];

  return (
    <span
      onClick={(e) => {
        if (onClick) {
          e.stopPropagation();
          onClick();
        }
      }}
      className={cn(
        "inline-flex items-center rounded border font-semibold uppercase tracking-wide transition-all",
        size === "sm" ? "px-1.5 py-0.5 text-[9px]" : "px-2 py-1 text-[10px]",
        onClick && "cursor-pointer hover:scale-105 active:scale-95",
        isActive && "ring-2 ring-offset-1 ring-offset-white dark:ring-offset-slate-900",
        config.color,
        config.bg,
        isActive && "ring-current"
      )}
      title={onClick ? "Click to filter by scope" : undefined}
    >
      {config.label}
    </span>
  );
}

function CategoryPill({
  category,
  onClick,
  isActive,
  size = "sm",
}: {
  category: MemoryCategory;
  onClick?: () => void;
  isActive?: boolean;
  size?: "sm" | "md";
}) {
  const config = CATEGORY_CONFIG[category];

  return (
    <span
      onClick={(e) => {
        if (onClick) {
          e.stopPropagation();
          onClick();
        }
      }}
      className={cn(
        "inline-flex items-center gap-1 rounded border font-semibold tracking-wide transition-all",
        size === "sm" ? "px-1.5 py-0.5 text-[9px]" : "px-2 py-1 text-[10px]",
        onClick && "cursor-pointer hover:scale-105 active:scale-95",
        isActive && "ring-2 ring-offset-1 ring-offset-white dark:ring-offset-slate-900",
        config.color,
        config.bg,
        isActive && "ring-current"
      )}
      title={onClick ? "Click to filter by category" : undefined}
    >
      <span>{config.icon}</span>
      <span className="uppercase">{config.label}</span>
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// RELEVANCE BADGE (for search results)
// ─────────────────────────────────────────────────────────────────────────────

function RelevanceBadge({ score }: { score: number }) {
  const percentage = Math.round(score * 100);
  const color =
    percentage >= 80
      ? "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10"
      : percentage >= 60
        ? "text-blue-600 dark:text-blue-400 bg-blue-500/10"
        : "text-slate-600 dark:text-slate-400 bg-slate-500/10";

  return (
    <Tooltip content={`Semantic similarity: ${percentage}%`}>
      <span
        className={cn(
          "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold tabular-nums cursor-help",
          color
        )}
      >
        <Sparkles className="h-2.5 w-2.5" />
        {percentage}%
      </span>
    </Tooltip>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// EXPANDED ROW CONTENT (inline accordion)
// ─────────────────────────────────────────────────────────────────────────────

function ExpandedRowContent({
  episode,
  onDelete,
  isDeleting,
}: {
  episode: MemoryEpisode;
  onDelete: () => void;
  isDeleting: boolean;
}) {
  const categoryConfig = CATEGORY_CONFIG[episode.category];

  return (
    <div className="p-5 space-y-5">
      {/* Three-column layout: Content | Stats | Meta */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_200px_220px] gap-5">
        {/* CONTENT PANE */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            <ScopePill scope={episode.scope} size="md" />
            <CategoryPill category={episode.category} size="md" />
            <span className="px-2 py-1 rounded text-[10px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 uppercase">
              {episode.source}
            </span>
          </div>

          <div className="p-4 rounded-lg bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
            <p className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap leading-relaxed">
              {episode.content}
            </p>
          </div>

          {/* Entity Tags */}
          {episode.entities.length > 0 && (
            <div>
              <h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">
                Entities
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {episode.entities.map((entity, i) => (
                  <span
                    key={i}
                    className="px-2 py-1 text-[10px] rounded-full bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700"
                  >
                    {entity}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* STATS PANE */}
        <div className="space-y-3">
          <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-400 border-b border-slate-200 dark:border-slate-700 pb-2">
            Usage Stats
          </h4>
          <div className="grid grid-cols-2 gap-2">
            {episode.loaded_count !== undefined && (
              <div className="p-2.5 rounded-lg bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
                <div className="flex items-center gap-1.5 text-slate-500 mb-1">
                  <Eye className="h-3 w-3" />
                  <span className="text-[9px] uppercase tracking-wide font-semibold">Loaded</span>
                </div>
                <p className="text-lg font-bold font-mono tabular-nums text-slate-700 dark:text-slate-200">
                  {episode.loaded_count}
                </p>
              </div>
            )}
            {episode.referenced_count !== undefined && (
              <div className="p-2.5 rounded-lg bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
                <div className="flex items-center gap-1.5 text-slate-500 mb-1">
                  <MessageCircle className="h-3 w-3" />
                  <span className="text-[9px] uppercase tracking-wide font-semibold">Cited</span>
                </div>
                <p className="text-lg font-bold font-mono tabular-nums text-slate-700 dark:text-slate-200">
                  {episode.referenced_count}
                </p>
              </div>
            )}
            {episode.success_count !== undefined && (
              <div className="p-2.5 rounded-lg bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
                <div className="flex items-center gap-1.5 text-slate-500 mb-1">
                  <ThumbsUp className="h-3 w-3" />
                  <span className="text-[9px] uppercase tracking-wide font-semibold">Success</span>
                </div>
                <p className="text-lg font-bold font-mono tabular-nums text-slate-700 dark:text-slate-200">
                  {episode.success_count}
                </p>
              </div>
            )}
            {episode.utility_score !== undefined && (
              <div className="p-2.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800">
                <div className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 mb-1">
                  <Sparkles className="h-3 w-3" />
                  <span className="text-[9px] uppercase tracking-wide font-semibold">Utility</span>
                </div>
                <p className="text-lg font-bold font-mono tabular-nums text-emerald-700 dark:text-emerald-300">
                  {(episode.utility_score * 100).toFixed(0)}%
                </p>
              </div>
            )}
          </div>

          {/* No stats available */}
          {episode.loaded_count === undefined &&
            episode.referenced_count === undefined &&
            episode.success_count === undefined &&
            episode.utility_score === undefined && (
              <p className="text-xs text-slate-400 italic">No usage data yet</p>
            )}
        </div>

        {/* META PANE */}
        <div className="space-y-3">
          <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-400 border-b border-slate-200 dark:border-slate-700 pb-2">
            Metadata
          </h4>
          <div className="space-y-2 text-[11px]">
            <div className="flex justify-between items-center">
              <span className="text-slate-500">ID</span>
              <div className="flex items-center gap-1">
                <code className="font-mono text-slate-600 dark:text-slate-300 truncate max-w-[140px]">
                  {episode.uuid}
                </code>
                <CopyButton text={episode.uuid} />
              </div>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Created</span>
              <span className="font-mono tabular-nums text-slate-600 dark:text-slate-300">
                {new Date(episode.created_at).toLocaleString()}
              </span>
            </div>
            {episode.scope_id && (
              <div className="flex justify-between">
                <span className="text-slate-500">Scope ID</span>
                <code className="font-mono text-slate-600 dark:text-slate-300 truncate max-w-[140px]">
                  {episode.scope_id}
                </code>
              </div>
            )}
          </div>

          {/* Delete button */}
          <div className="pt-3 border-t border-slate-200 dark:border-slate-700">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              disabled={isDeleting}
              className={cn(
                "w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-colors",
                "bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400",
                "hover:bg-red-100 dark:hover:bg-red-900/30",
                "border border-red-200 dark:border-red-800",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {isDeleting ? (
                <div className="w-3.5 h-3.5 border-2 border-red-500 border-t-transparent rounded-full animate-spin" />
              ) : (
                <Trash2 className="h-3.5 w-3.5" />
              )}
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// DELETE CONFIRMATION MODAL
// ─────────────────────────────────────────────────────────────────────────────

function DeleteModal({
  isOpen,
  onClose,
  onConfirm,
  count,
  isDeleting,
}: {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  count: number;
  isDeleting: boolean;
}) {
  const [acknowledged, setAcknowledged] = useState(false);

  useEffect(() => {
    if (!isOpen) setAcknowledged(false);
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" data-testid="delete-modal">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md mx-4 rounded-xl bg-white dark:bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-full bg-red-100 dark:bg-red-900/30">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              Delete {count} {count === 1 ? "Memory" : "Memories"}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            This will permanently delete {count} {count === 1 ? "memory" : "memories"} from the
            knowledge graph. This action cannot be undone.
          </p>
          <label className="flex items-start gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              className="mt-1 w-4 h-4 rounded border-slate-300 dark:border-slate-600 text-red-600 focus:ring-red-500"
            />
            <span className="text-sm text-slate-700 dark:text-slate-300">
              I understand this action is permanent
            </span>
          </label>
        </div>

        <div className="flex items-center justify-end gap-3 p-4 border-t border-slate-200 dark:border-slate-800">
          <button
            onClick={onClose}
            disabled={isDeleting}
            className="px-4 py-2 rounded-lg text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={() => acknowledged && onConfirm()}
            disabled={!acknowledged || isDeleting}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-red-600 hover:bg-red-700 text-white disabled:opacity-50 flex items-center gap-2"
          >
            {isDeleting ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Deleting...
              </>
            ) : (
              "Delete"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// BULK ACTIONS TOOLBAR
// ─────────────────────────────────────────────────────────────────────────────

function BulkToolbar({
  selectedCount,
  onDelete,
  onExport,
  onClear,
  isDeleting,
}: {
  selectedCount: number;
  onDelete: () => void;
  onExport: () => void;
  onClear: () => void;
  isDeleting: boolean;
}) {
  if (selectedCount === 0) return null;

  return (
    <div
      className={cn(
        "fixed bottom-6 left-1/2 -translate-x-1/2 z-40",
        "flex items-center gap-3 px-4 py-3 rounded-xl",
        "bg-slate-900 dark:bg-slate-800 shadow-2xl",
        "border border-slate-700 dark:border-slate-600",
        "animate-in slide-in-from-bottom-4 fade-in duration-200"
      )}
    >
      <span className="flex items-center gap-2 text-sm font-medium text-white">
        <span className="px-2 py-0.5 rounded-full bg-emerald-500 text-xs tabular-nums">
          {selectedCount}
        </span>
        selected
      </span>

      <div className="w-px h-6 bg-slate-600" />

      <button
        onClick={onDelete}
        disabled={isDeleting}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-red-600 hover:bg-red-700 text-white disabled:opacity-50"
      >
        {isDeleting ? (
          <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
        ) : (
          <Trash2 className="w-4 h-4" />
        )}
        Delete
      </button>

      <button
        onClick={onExport}
        disabled={isDeleting}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-700 hover:bg-slate-600 text-white disabled:opacity-50"
      >
        <Download className="w-4 h-4" />
        Export
      </button>

      <div className="w-px h-6 bg-slate-600" />

      <button
        onClick={onClear}
        disabled={isDeleting}
        className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 disabled:opacity-50"
        title="Clear selection"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN CONTENT COMPONENT
// ─────────────────────────────────────────────────────────────────────────────

function MemoryPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tableRef = useRef<HTMLDivElement>(null);

  // URL-synced filter state
  const groupId = searchParams.get("group") || undefined;
  const scope = (searchParams.get("scope") as MemoryScope) || undefined;
  const category = (searchParams.get("category") as MemoryCategory) || undefined;
  const sortBy = (searchParams.get("sort") as MemorySortBy) || "created_at";

  // Local state
  const [refreshInterval, setRefreshInterval] = useState<RefreshInterval>(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [sortField, setSortField] = useState<SortField>("created_at");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [focusedRowIndex, setFocusedRowIndex] = useState<number>(-1);
  const [expandedMemoryId, setExpandedMemoryId] = useState<string | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  // Use the memory hook
  const {
    stats,
    episodes,
    searchResults,
    hasMore,
    loadMore,
    isFetchingMore,
    isLoadingEpisodes,
    isSearching,
    selectedIds,
    toggleSelect,
    selectAll,
    clearSelection,
    isAllSelected,
    searchQuery,
    setSearchQuery,
    deleteOne,
    deleteSelected,
    exportSelected,
    isDeleting,
    refresh,
  } = useMemory({ groupId, scope, category, sortBy });

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

  // Auto-refresh effect
  useEffect(() => {
    if (refreshInterval === 0) return;
    const intervalId = setInterval(() => {
      setIsRefreshing(true);
      refresh();
      setTimeout(() => setIsRefreshing(false), 500);
    }, refreshInterval);
    return () => clearInterval(intervalId);
  }, [refreshInterval, refresh]);

  // URL param updates
  const updateParams = useCallback(
    (updates: Record<string, string | undefined>) => {
      const params = new URLSearchParams(searchParams.toString());
      Object.entries(updates).forEach(([key, value]) => {
        if (value === undefined) {
          params.delete(key);
        } else {
          params.set(key, value);
        }
      });
      router.push(`/memory?${params.toString()}`, { scroll: false });
    },
    [router, searchParams]
  );

  const handleScopeChange = useCallback(
    (newScope: MemoryScope | undefined) => updateParams({ scope: newScope }),
    [updateParams]
  );

  const handleCategoryChange = useCallback(
    (newCategory: MemoryCategory | undefined) => updateParams({ category: newCategory }),
    [updateParams]
  );

  const handleRefreshChange = useCallback((interval: RefreshInterval) => {
    setRefreshInterval(interval);
    localStorage.setItem(REFRESH_STORAGE_KEY, String(interval));
  }, []);

  const handleSort = useCallback(
    (field: SortField) => {
      const newDirection = sortField === field && sortDirection === "desc" ? "asc" : "desc";
      setSortField(field);
      setSortDirection(newDirection);
      localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify({ field, direction: newDirection }));
    },
    [sortField, sortDirection]
  );

  // Toggle row expansion
  const handleToggleExpand = useCallback((id: string) => {
    setExpandedMemoryId((prev) => (prev === id ? null : id));
  }, []);

  // Determine display items (search results or episodes)
  const isSearchMode = searchQuery.length >= 2;
  const displayItems = useMemo(() => {
    if (isSearchMode && searchResults) {
      return searchResults.results.map((r) => ({
        uuid: r.uuid,
        name: "",
        content: r.content,
        source: r.source,
        category: "coding_standard" as MemoryCategory,
        scope: "global" as MemoryScope,
        scope_id: null,
        source_description: "",
        created_at: r.created_at,
        valid_at: r.created_at,
        entities: r.facts || [],
        relevance_score: r.relevance_score,
        utility_score: undefined as number | undefined,
        loaded_count: undefined as number | undefined,
        referenced_count: undefined as number | undefined,
        success_count: undefined as number | undefined,
      }));
    }
    return episodes;
  }, [isSearchMode, searchResults, episodes]);

  // Sort items
  const sortedItems = useMemo(() => {
    const items = [...displayItems];
    items.sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "scope":
          cmp = a.scope.localeCompare(b.scope);
          break;
        case "category":
          cmp = a.category.localeCompare(b.category);
          break;
        case "content":
          cmp = a.content.localeCompare(b.content);
          break;
        case "created_at":
          cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
          break;
        case "utility":
          cmp = (a.utility_score || 0) - (b.utility_score || 0);
          break;
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });
    return items;
  }, [displayItems, sortField, sortDirection]);

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!sortedItems.length) return;

      switch (e.key) {
        case "ArrowDown":
        case "j":
          e.preventDefault();
          setFocusedRowIndex((prev) => Math.min(prev + 1, sortedItems.length - 1));
          break;
        case "ArrowUp":
        case "k":
          e.preventDefault();
          setFocusedRowIndex((prev) => Math.max(prev - 1, 0));
          break;
        case "Enter":
        case " ":
          e.preventDefault();
          if (focusedRowIndex >= 0 && focusedRowIndex < sortedItems.length) {
            handleToggleExpand(sortedItems[focusedRowIndex].uuid);
          }
          break;
        case "Escape":
          e.preventDefault();
          setExpandedMemoryId(null);
          break;
      }
    },
    [sortedItems, focusedRowIndex, handleToggleExpand]
  );

  // Scroll-based load more
  const handleScroll = useCallback(() => {
    if (!tableRef.current || isFetchingMore || !hasMore || isSearchMode) return;
    const { scrollTop, scrollHeight, clientHeight } = tableRef.current;
    if (scrollHeight - scrollTop - clientHeight < 500) {
      loadMore();
    }
  }, [hasMore, isFetchingMore, loadMore, isSearchMode]);

  // Delete handlers
  const handleDeleteClick = useCallback((id: string) => {
    setPendingDeleteId(id);
    setShowDeleteModal(true);
  }, []);

  const handleBulkDeleteClick = useCallback(() => {
    setPendingDeleteId(null);
    setShowDeleteModal(true);
  }, []);

  const handleConfirmDelete = useCallback(async () => {
    if (pendingDeleteId) {
      await deleteOne(pendingDeleteId);
      if (expandedMemoryId === pendingDeleteId) {
        setExpandedMemoryId(null);
      }
    } else {
      await deleteSelected();
      setExpandedMemoryId(null);
    }
    setShowDeleteModal(false);
    setPendingDeleteId(null);
  }, [pendingDeleteId, deleteOne, deleteSelected, expandedMemoryId]);

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      {/* Sub-header: Search & Controls */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/80 space-y-3">
        <div className="flex items-center gap-3">
          {/* Search */}
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder="Semantic search..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-9 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-500"
              data-testid="memory-search"
            />
            {searchQuery && !isSearching && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              >
                <X className="h-4 w-4" />
              </button>
            )}
            {isSearching && (
              <div className="absolute right-3 top-1/2 -translate-y-1/2">
                <div className="w-4 h-4 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
              </div>
            )}
          </div>

          {/* Auto-refresh */}
          <div className="flex items-center gap-1.5">
            <RefreshCw
              className={cn(
                "h-4 w-4",
                isRefreshing ? "animate-spin text-emerald-500" : "text-slate-400"
              )}
            />
            <select
              value={refreshInterval}
              onChange={(e) =>
                handleRefreshChange(parseInt(e.target.value, 10) as RefreshInterval)
              }
              className={cn(
                "px-2 py-1.5 rounded-md border text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500/40",
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
        </div>

        {/* Active Filters */}
        <div className="flex items-center gap-2 flex-wrap">
          {scope && (
            <span className="flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
              Scope: {SCOPE_CONFIG[scope].label}
              <button
                onClick={() => handleScopeChange(undefined)}
                className="p-0.5 rounded-full hover:bg-slate-200 dark:hover:bg-slate-700"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          )}
          {category && (
            <span className="flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
              {CATEGORY_CONFIG[category].icon} {CATEGORY_CONFIG[category].label}
              <button
                onClick={() => handleCategoryChange(undefined)}
                className="p-0.5 rounded-full hover:bg-slate-200 dark:hover:bg-slate-700"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          )}
          {isSearchMode && searchResults && (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {searchResults.count} results for "{searchQuery}"
            </span>
          )}
        </div>
      </div>

      {/* Table */}
      <div
        ref={tableRef}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        onScroll={handleScroll}
        className="flex-1 overflow-auto focus:outline-none"
      >
        {/* Table Header */}
        <div className="sticky top-0 z-10 bg-slate-50/95 dark:bg-slate-800/95 backdrop-blur-sm border-b border-slate-200 dark:border-slate-700">
          <div className="grid grid-cols-[40px_70px_90px_1fr_80px_70px_32px] gap-2 px-3 py-2 items-center">
            <button
              onClick={isAllSelected ? clearSelection : selectAll}
              className={cn(
                "w-5 h-5 rounded border flex items-center justify-center transition-colors",
                isAllSelected
                  ? "bg-emerald-500 border-emerald-500 text-white"
                  : "border-slate-300 dark:border-slate-600 hover:border-emerald-400"
              )}
              data-testid="select-all-checkbox"
            >
              {isAllSelected && <Check className="w-3 h-3" />}
            </button>

            <SortableHeader label="Scope" field="scope" currentField={sortField} direction={sortDirection} onSort={handleSort} />
            <SortableHeader label="Category" field="category" currentField={sortField} direction={sortDirection} onSort={handleSort} />
            <SortableHeader label="Content" field="content" currentField={sortField} direction={sortDirection} onSort={handleSort} />
            <SortableHeader label="Time" field="created_at" currentField={sortField} direction={sortDirection} onSort={handleSort} align="right" />
            <SortableHeader label="Utility" field="utility" currentField={sortField} direction={sortDirection} onSort={handleSort} align="right" />
            <div />
          </div>
        </div>

        {/* Loading State */}
        {isLoadingEpisodes && (
          <div className="divide-y divide-slate-100 dark:divide-slate-800/50">
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="grid grid-cols-[40px_70px_90px_1fr_80px_70px_32px] gap-2 px-3 py-2.5 items-center">
                <div className="h-4 w-4 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-5 w-14 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-5 w-16 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-4 w-full max-w-md rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-4 w-12 rounded bg-slate-200 dark:bg-slate-700 animate-pulse ml-auto" />
                <div className="h-4 w-10 rounded bg-slate-200 dark:bg-slate-700 animate-pulse ml-auto" />
                <div className="h-4 w-4 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              </div>
            ))}
          </div>
        )}

        {/* Empty State */}
        {!isLoadingEpisodes && sortedItems.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="p-4 rounded-full bg-slate-100 dark:bg-slate-800 mb-4">
              <Database className="w-8 h-8 text-slate-400" />
            </div>
            <h3 className="text-lg font-medium text-slate-900 dark:text-slate-100 mb-1">
              No memories found
            </h3>
            <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm">
              {isSearchMode
                ? `No results for "${searchQuery}"`
                : "Memories will appear here as they are created"}
            </p>
          </div>
        )}

        {/* Table Rows with Accordion Expansion */}
        {!isLoadingEpisodes && sortedItems.length > 0 && (
          <div className="divide-y divide-slate-100 dark:divide-slate-800/50">
            {sortedItems.map((item, index) => {
              const isSelected = selectedIds.has(item.uuid);
              const isFocused = focusedRowIndex === index;
              const isExpanded = expandedMemoryId === item.uuid;
              const hasRelevance = "relevance_score" in item && item.relevance_score !== undefined;

              return (
                <div key={item.uuid} className={cn(isExpanded && "bg-slate-50/50 dark:bg-slate-800/20")}>
                  {/* ROW */}
                  <button
                    onClick={() => handleToggleExpand(item.uuid)}
                    className={cn(
                      "w-full grid grid-cols-[40px_70px_90px_1fr_80px_70px_32px] gap-2 px-3 py-2.5 items-center text-left transition-colors",
                      "hover:bg-slate-50 dark:hover:bg-slate-800/30",
                      isFocused && "bg-blue-50 dark:bg-blue-950/20 ring-1 ring-inset ring-blue-200 dark:ring-blue-800",
                      isExpanded && "bg-emerald-50/50 dark:bg-emerald-950/10",
                      isSelected && !isExpanded && "bg-emerald-50/30 dark:bg-emerald-950/5"
                    )}
                    data-testid="memory-row"
                  >
                    {/* Checkbox */}
                    <div
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleSelect(item.uuid);
                      }}
                      className={cn(
                        "w-5 h-5 rounded border flex items-center justify-center transition-colors cursor-pointer",
                        isSelected
                          ? "bg-emerald-500 border-emerald-500 text-white"
                          : "border-slate-300 dark:border-slate-600 hover:border-emerald-400"
                      )}
                    >
                      {isSelected && <Check className="w-3 h-3" />}
                    </div>

                    {/* Scope */}
                    <ScopePill
                      scope={item.scope}
                      onClick={() => handleScopeChange(scope === item.scope ? undefined : item.scope)}
                      isActive={scope === item.scope}
                    />

                    {/* Category */}
                    <CategoryPill
                      category={item.category}
                      onClick={() => handleCategoryChange(category === item.category ? undefined : item.category)}
                      isActive={category === item.category}
                    />

                    {/* Content */}
                    <div className="min-w-0 flex items-center gap-2">
                      <span className="text-xs text-slate-700 dark:text-slate-300 truncate">
                        {item.content.slice(0, 100)}
                        {item.content.length > 100 && "..."}
                      </span>
                      {hasRelevance && <RelevanceBadge score={(item as { relevance_score: number }).relevance_score} />}
                    </div>

                    {/* Time */}
                    <div className="text-right">
                      <span className="text-[11px] font-mono tabular-nums text-slate-500 dark:text-slate-400">
                        {formatRelativeTime(item.created_at)}
                      </span>
                    </div>

                    {/* Utility Score */}
                    <div className="text-right">
                      {item.utility_score !== undefined ? (
                        <span
                          className={cn(
                            "text-[11px] font-mono tabular-nums font-medium",
                            item.utility_score >= 0.7
                              ? "text-emerald-600 dark:text-emerald-400"
                              : item.utility_score >= 0.4
                                ? "text-amber-600 dark:text-amber-400"
                                : "text-slate-500 dark:text-slate-400"
                          )}
                        >
                          {(item.utility_score * 100).toFixed(0)}%
                        </span>
                      ) : (
                        <span className="text-[11px] text-slate-400">—</span>
                      )}
                    </div>

                    {/* Expand indicator */}
                    <div className="flex items-center justify-end">
                      <ChevronDown
                        className={cn(
                          "h-4 w-4 text-slate-400 transition-transform duration-200",
                          isExpanded && "rotate-180"
                        )}
                      />
                    </div>
                  </button>

                  {/* EXPANDED CONTENT - Accordion animation */}
                  <div
                    className={cn(
                      "grid transition-all duration-300 ease-out",
                      isExpanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
                    )}
                  >
                    <div className="overflow-hidden">
                      <div className="border-t border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/80">
                        <ExpandedRowContent
                          episode={item as MemoryEpisode}
                          onDelete={() => handleDeleteClick(item.uuid)}
                          isDeleting={isDeleting && pendingDeleteId === item.uuid}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}

            {/* Loading more indicator */}
            {isFetchingMore && (
              <div className="py-4 text-center">
                <div className="inline-flex items-center gap-2 text-sm text-slate-500">
                  <div className="w-4 h-4 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
                  Loading more...
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Bulk Actions Toolbar */}
      <BulkToolbar
        selectedCount={selectedIds.size}
        onDelete={handleBulkDeleteClick}
        onExport={exportSelected}
        onClear={clearSelection}
        isDeleting={isDeleting}
      />

      {/* Delete Modal */}
      <DeleteModal
        isOpen={showDeleteModal}
        onClose={() => {
          setShowDeleteModal(false);
          setPendingDeleteId(null);
        }}
        onConfirm={handleConfirmDelete}
        count={pendingDeleteId ? 1 : selectedIds.size}
        isDeleting={isDeleting}
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LOADING STATE
// ─────────────────────────────────────────────────────────────────────────────

function LoadingState() {
  return (
    <div className="flex h-[calc(100vh-56px)]">
      <div className="flex-1 p-4">
        <div className="animate-pulse space-y-4">
          <div className="h-10 bg-slate-200 dark:bg-slate-700 rounded-lg" />
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-12 bg-slate-200 dark:bg-slate-700 rounded" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN PAGE
// ─────────────────────────────────────────────────────────────────────────────

export default function MemoryPage() {
  const { stats, isLoadingStats } = useMemory({});

  const categoryStats = useMemo(() => {
    if (!stats?.by_category) return [];
    return stats.by_category.slice(0, 4);
  }, [stats]);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Page Header */}
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
        <div className="px-4 lg:px-6">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-emerald-100 dark:bg-emerald-900/30">
                  <Brain className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                </div>
                <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100 tracking-tight">
                  Memory
                </h1>
              </div>

              <div className="hidden sm:flex items-center gap-3 text-xs font-mono tabular-nums">
                <span className="text-slate-500 dark:text-slate-400">
                  {isLoadingStats ? "..." : stats?.total ?? 0} total
                </span>
                {categoryStats.length > 0 && (
                  <>
                    <span className="text-slate-300 dark:text-slate-600">|</span>
                    {categoryStats.map((cat) => (
                      <span
                        key={cat.category}
                        className={cn("flex items-center gap-1", CATEGORY_CONFIG[cat.category].color)}
                      >
                        {CATEGORY_CONFIG[cat.category].icon}
                        {cat.count}
                      </span>
                    ))}
                  </>
                )}
              </div>
            </div>

            <div className="hidden lg:flex items-center gap-2 text-[10px] text-slate-400">
              <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono">j/k</span>
              <span>navigate</span>
              <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono">Enter</span>
              <span>expand</span>
              <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono">Esc</span>
              <span>collapse</span>
            </div>
          </div>
        </div>
      </header>

      <Suspense fallback={<LoadingState />}>
        <MemoryPageContent />
      </Suspense>
    </div>
  );
}
