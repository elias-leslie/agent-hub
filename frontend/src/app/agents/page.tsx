"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  RefreshCw,
  Search,
  AlertCircle,
  MoreVertical,
  Play,
  Copy,
  Archive,
  ChevronDown,
  Zap,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

interface Agent {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  primary_model_id: string;
  fallback_models: string[];
  mandate_tags: string[];
  temperature: number;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

interface AgentListResponse {
  agents: Agent[];
  total: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────────────────────────────────

async function fetchAgents(activeOnly = true): Promise<AgentListResponse> {
  const params = new URLSearchParams();
  params.set("active_only", String(activeOnly));

  const res = await fetch(`/api/agents?${params}`);
  if (!res.ok) {
    throw new Error("Failed to fetch agents");
  }
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPONENTS
// ─────────────────────────────────────────────────────────────────────────────

function ModelPill({ model }: { model: string }) {
  const isClaude = model.toLowerCase().includes("claude");
  const shortName = model
    .replace("claude-", "")
    .replace("gemini-", "")
    .replace("-20250514", "")
    .slice(0, 12);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide border",
        isClaude
          ? "border-purple-400/60 text-purple-600 dark:text-purple-400 bg-purple-50/80 dark:bg-purple-950/40"
          : "border-emerald-400/60 text-emerald-600 dark:text-emerald-400 bg-emerald-50/80 dark:bg-emerald-950/40"
      )}
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

function StatusBadge({ isActive }: { isActive: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide",
        isActive
          ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400"
          : "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400"
      )}
    >
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-full",
          isActive ? "bg-emerald-500" : "bg-slate-400"
        )}
      />
      {isActive ? "Active" : "Inactive"}
    </span>
  );
}

function TagsList({ tags }: { tags: string[] }) {
  if (tags.length === 0) return <span className="text-slate-400">—</span>;

  return (
    <div className="flex flex-wrap gap-1">
      {tags.slice(0, 3).map((tag) => (
        <span
          key={tag}
          className="px-1.5 py-0.5 rounded text-[10px] bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 font-medium"
        >
          {tag}
        </span>
      ))}
      {tags.length > 3 && (
        <span className="text-[10px] text-slate-400">+{tags.length - 3}</span>
      )}
    </div>
  );
}

function AgentActionsMenu({ agent }: { agent: Agent }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
      >
        <MoreVertical className="h-4 w-4 text-slate-400" />
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 top-8 z-50 w-40 py-1 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-lg">
            <button
              onClick={() => {
                window.location.href = `/agents/${agent.slug}/playground`;
                setOpen(false);
              }}
              className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left hover:bg-slate-50 dark:hover:bg-slate-700"
            >
              <Play className="h-3.5 w-3.5" />
              Playground
            </button>
            <button
              onClick={() => {
                navigator.clipboard.writeText(agent.slug);
                setOpen(false);
              }}
              className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left hover:bg-slate-50 dark:hover:bg-slate-700"
            >
              <Copy className="h-3.5 w-3.5" />
              Copy Slug
            </button>
            <button
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20"
            >
              <Archive className="h-3.5 w-3.5" />
              Archive
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN PAGE
// ─────────────────────────────────────────────────────────────────────────────

export default function AgentsPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [showInactive, setShowInactive] = useState(false);

  const { data, isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: ["agents", { activeOnly: !showInactive }],
    queryFn: () => fetchAgents(!showInactive),
  });

  const filteredAgents = useMemo(() => {
    if (!data?.agents) return [];

    if (!searchQuery) return data.agents;

    const query = searchQuery.toLowerCase();
    return data.agents.filter(
      (a) =>
        a.slug.toLowerCase().includes(query) ||
        a.name.toLowerCase().includes(query) ||
        a.description?.toLowerCase().includes(query) ||
        a.mandate_tags.some((t) => t.toLowerCase().includes(query))
    );
  }, [data?.agents, searchQuery]);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* HEADER */}
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Bot className="h-5 w-5 text-slate-600 dark:text-slate-400" />
                <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100 tracking-tight">
                  Agents
                </h1>
              </div>
              <div className="flex items-center gap-3 text-xs font-mono tabular-nums">
                <span className="text-slate-500 dark:text-slate-400">
                  {data?.total ?? 0} total
                </span>
              </div>
            </div>

            {/* Controls */}
            <div className="flex items-center gap-2">
              {/* Search */}
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search agents..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8 pr-3 py-1.5 w-48 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500"
                />
              </div>

              {/* Show inactive toggle */}
              <label className="flex items-center gap-2 px-2.5 py-1.5 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={showInactive}
                  onChange={(e) => setShowInactive(e.target.checked)}
                  className="rounded border-slate-300 dark:border-slate-600"
                />
                <span className="text-slate-600 dark:text-slate-400">Show inactive</span>
              </label>

              {/* Refresh */}
              <button
                onClick={() => refetch()}
                disabled={isRefetching}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
              >
                <RefreshCw
                  className={cn("h-3.5 w-3.5", isRefetching && "animate-spin")}
                />
                Refresh
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-5">
        {/* Error State */}
        {error && (
          <div className="flex items-center gap-2 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 mb-5">
            <AlertCircle className="h-4 w-4" />
            <p className="text-xs font-medium">Failed to load agents</p>
          </div>
        )}

        {/* Loading */}
        {isLoading && (
          <div className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
            <div className="h-10 bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-700" />
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="grid grid-cols-[200px_1fr_140px_100px_100px_100px_40px] gap-3 px-4 py-3 border-b border-slate-100 dark:border-slate-800/50"
              >
                <div className="h-4 w-32 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-4 w-48 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-5 w-20 rounded-full bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-4 w-16 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-4 w-12 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-4 w-12 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-4 w-4 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              </div>
            ))}
          </div>
        )}

        {/* AGENTS TABLE */}
        {data && (
          <>
            {filteredAgents.length === 0 ? (
              <div className="text-center py-20 text-slate-400">
                <Bot className="h-10 w-10 mx-auto mb-3 opacity-30" />
                <p className="text-sm font-medium">No agents found</p>
              </div>
            ) : (
              <div className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
                {/* TABLE HEADER */}
                <div className="bg-slate-50/95 dark:bg-slate-800/95 border-b border-slate-200 dark:border-slate-700">
                  <div className="grid grid-cols-[200px_1fr_140px_100px_100px_100px_40px] gap-3 px-4 py-2.5 items-center">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Agent
                    </span>
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Description
                    </span>
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Primary Model
                    </span>
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Mandate Tags
                    </span>
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Status
                    </span>
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 text-right">
                      Version
                    </span>
                    <div />
                  </div>
                </div>

                {/* TABLE BODY */}
                <div className="divide-y divide-slate-100 dark:divide-slate-800/50">
                  {filteredAgents.map((agent) => (
                    <div
                      key={agent.id}
                      className="grid grid-cols-[200px_1fr_140px_100px_100px_100px_40px] gap-3 px-4 py-3 items-center hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors"
                    >
                      {/* Agent Name & Slug */}
                      <div className="min-w-0">
                        <a
                          href={`/agents/${agent.slug}`}
                          className="text-sm font-semibold text-slate-800 dark:text-slate-100 hover:text-blue-600 dark:hover:text-blue-400 truncate block"
                        >
                          {agent.name}
                        </a>
                        <span className="text-[10px] text-slate-400 font-mono">
                          {agent.slug}
                        </span>
                      </div>

                      {/* Description */}
                      <div className="min-w-0">
                        <span className="text-xs text-slate-500 dark:text-slate-400 truncate block">
                          {agent.description || "—"}
                        </span>
                      </div>

                      {/* Primary Model */}
                      <ModelPill model={agent.primary_model_id} />

                      {/* Mandate Tags */}
                      <TagsList tags={agent.mandate_tags} />

                      {/* Status */}
                      <StatusBadge isActive={agent.is_active} />

                      {/* Version */}
                      <div className="text-right">
                        <span className="text-xs font-mono tabular-nums text-slate-500">
                          v{agent.version}
                        </span>
                      </div>

                      {/* Actions */}
                      <AgentActionsMenu agent={agent} />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
