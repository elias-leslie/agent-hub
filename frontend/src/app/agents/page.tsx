"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  Archive,
  Bot,
  CheckCircle2,
  Plus,
  RefreshCw,
  Search,
  X,
} from "lucide-react";

import { PlatformContextPanel } from "@/components/PlatformContextPanel";
import { fetchAgents, fetchAgentMetrics } from "@/lib/api";
import { fetchApi } from "@/lib/api-config";
import { cn } from "@/lib/utils";
import { AgentsTable } from "./components/AgentsTable";
import { useAgentFiltering } from "./hooks/useAgentFiltering";
import type {
  Agent,
  AgentMetrics,
  AgentMetricsResponse,
  SortDirection,
  SortField,
} from "./lib/types";

export default function AgentsPage() {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [sortField, setSortField] = useState<SortField>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [archiveCandidate, setArchiveCandidate] = useState<Agent | null>(null);
  const [archiveState, setArchiveState] = useState<{
    status: "idle" | "saving" | "success" | "error";
    message: string | null;
  }>({ status: "idle", message: null });

  const handleSort = useCallback(
    (field: SortField) => {
      if (sortField === field) {
        setSortDirection((direction) => (direction === "desc" ? "asc" : "desc"));
      } else {
        setSortField(field);
        setSortDirection("desc");
      }
    },
    [sortField],
  );

  const { data, isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: ["agents", { activeOnly: !showInactive }],
    queryFn: () => fetchAgents(!showInactive),
  });

  const { data: metricsData } = useQuery<AgentMetricsResponse>({
    queryKey: ["agent-metrics"],
    queryFn: () => fetchAgentMetrics(),
    refetchInterval: 60000,
  });

  const filteredAgents = useAgentFiltering({
    agents: data?.agents,
    searchQuery,
    sortField,
    sortDirection,
    metricsData: metricsData?.metrics,
  });

  const getMetrics = useCallback(
    (slug: string): AgentMetrics | null => metricsData?.metrics?.[slug] ?? null,
    [metricsData],
  );

  const handleClone = useCallback(
    (agent: Agent) => {
      const params = new URLSearchParams({ clone: agent.slug });
      router.push(`/agents/new?${params}`);
    },
    [router],
  );

  const handleArchive = useCallback((agent: Agent) => {
    setArchiveCandidate(agent);
    setArchiveState({ status: "idle", message: null });
  }, []);

  const dismissArchiveMessage = useCallback(() => {
    setArchiveCandidate(null);
    setArchiveState({ status: "idle", message: null });
  }, []);

  const confirmArchive = useCallback(async () => {
    if (!archiveCandidate) {
      return;
    }

    setArchiveState({
      status: "saving",
      message: `Archiving ${archiveCandidate.name}...`,
    });

    try {
      const res = await fetchApi(`/api/agents/${archiveCandidate.slug}`, {
        method: "DELETE",
      });

      if (!res.ok) {
        throw new Error(`Failed to archive agent (${res.status})`);
      }

      setArchiveState({
        status: "success",
        message: `${archiveCandidate.name} archived. Hidden from the active list.`,
      });
      setArchiveCandidate(null);
      refetch();
    } catch (err) {
      console.error("Archive failed:", err);
      setArchiveState({
        status: "error",
        message: err instanceof Error ? err.message : "Failed to archive agent",
      });
    }
  }, [archiveCandidate, refetch]);

  const hasSearch = searchQuery.trim().length > 0;
  const catalogAgents = data?.agents?.filter((agent) => agent.slug !== "persona") ?? [];
  const visibleCount = filteredAgents.length;
  const totalCount = catalogAgents.length;
  const activeCount = catalogAgents.filter((agent) => agent.is_active).length;
  const listedCount = showInactive ? totalCount : activeCount;

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />
      <header className="page-header">
        <div className="page-container px-4 lg:px-8">
          <div className="page-header-row">
            <div className="page-title-group">
              <div className="page-title-icon">
                <Bot className="h-5 w-5" />
              </div>
              <div className="page-title-stack">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="page-title">Agents</h1>
                  <span className="page-pill">{visibleCount} shown</span>
                  <span className="text-xs text-slate-500">
                    of {listedCount} {showInactive ? "cataloged" : "active"}
                  </span>
                </div>
                <div className="page-meta">
                  <span>Manage active agents, compare runtime behavior, and shape shared platform context.</span>
                </div>
              </div>
            </div>

            <div className="page-toolbar">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search name, slug, or description..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  aria-label="Search agents"
                  className="control-input w-full py-2 pl-9 pr-9 text-sm sm:w-72"
                />
                {hasSearch && (
                  <button
                    type="button"
                    onClick={() => setSearchQuery("")}
                    aria-label="Clear search"
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-1 text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-slate-700/80 bg-slate-900/80 px-3 py-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={showInactive}
                  onChange={(e) => setShowInactive(e.target.checked)}
                  className="rounded border-slate-600 bg-slate-900"
                />
                <span className="text-slate-400">Show inactive</span>
              </label>

              <button
                type="button"
                onClick={() => refetch()}
                disabled={isRefetching}
                className="button-secondary px-3 py-2 text-sm disabled:opacity-50"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", isRefetching && "animate-spin")} />
                Refresh
              </button>

              <Link
                href="/agents/new"
                className="button-primary"
              >
                <Plus className="h-4 w-4" />
                New Agent
              </Link>
            </div>
          </div>
        </div>
      </header>

      <main className="page-frame">
        <div className="page-container">
        <PlatformContextPanel activeAgentCount={activeCount} />

        {archiveCandidate && (
          <div className="mb-5 mt-5 flex flex-col gap-3 rounded-2xl border border-amber-900/60 bg-amber-950/30 p-4 text-sm text-amber-100 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-2">
              <Archive className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="font-medium">Archive {archiveCandidate.name}?</p>
                <p className="text-amber-200/80">
                  This deactivates the agent and removes it from the default list. You can still find it later by showing inactive agents.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={dismissArchiveMessage}
                className="rounded-xl border border-amber-800 bg-transparent px-3 py-2 text-xs font-medium text-amber-100 hover:bg-amber-900/30 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmArchive}
                disabled={archiveState.status === "saving"}
                className="rounded-xl bg-amber-500 px-3 py-2 text-xs font-semibold text-slate-950 hover:bg-amber-400 disabled:opacity-60"
              >
                {archiveState.status === "saving" ? "Archiving..." : "Confirm archive"}
              </button>
            </div>
          </div>
        )}

        {archiveState.message && !archiveCandidate && (
          <div
            className={cn(
              "mb-5 mt-5 flex items-start gap-2 rounded-2xl border p-4 text-sm",
              archiveState.status === "success"
                ? "border-emerald-900/60 bg-emerald-950/30 text-emerald-300"
                : "border-red-900/60 bg-red-950/30 text-red-300",
            )}
          >
            {archiveState.status === "success" ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            ) : (
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            )}
            <div className="flex-1">
              <p className="font-medium">
                {archiveState.status === "success" ? "Archive complete" : "Archive failed"}
              </p>
              <p>{archiveState.message}</p>
            </div>
            <button
              type="button"
              onClick={dismissArchiveMessage}
              aria-label="Dismiss archive message"
              className="rounded p-1 hover:bg-slate-400/10"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {error && (
          <div className="mb-5 mt-5 flex flex-col gap-3 rounded-2xl border border-red-900/60 bg-red-950/20 p-4 text-red-300 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-2">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="text-sm font-medium">Failed to load agents</p>
                <p className="text-xs text-red-300/80">
                  {error instanceof Error ? error.message : "Check the API response and try again."}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => refetch()}
              className="rounded-xl border border-red-800 bg-transparent px-3 py-2 text-xs font-medium text-red-300 hover:bg-red-900/30 cursor-pointer"
            >
              Retry
            </button>
          </div>
        )}

        {isLoading && (
          <div className="table-surface">
            <div className="h-12 border-b border-slate-800/80 bg-slate-800/50" />
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="grid grid-cols-[220px_1fr_130px_130px_110px_40px] gap-3 border-b border-slate-800/50 px-5 py-4"
              >
                <div className="h-4 w-32 animate-pulse rounded bg-slate-700" />
                <div className="h-4 w-48 animate-pulse rounded bg-slate-700" />
                <div className="h-4 w-16 animate-pulse rounded bg-slate-700" />
                <div className="h-4 w-12 animate-pulse rounded bg-slate-700" />
                <div className="h-4 w-14 animate-pulse rounded bg-slate-700" />
                <div className="h-4 w-4 animate-pulse rounded bg-slate-700" />
              </div>
            ))}
          </div>
        )}

        {data && (
          <AgentsTable
            agents={filteredAgents}
            sortField={sortField}
            sortDirection={sortDirection}
            onSort={handleSort}
            getMetrics={getMetrics}
            onClone={handleClone}
            onArchive={handleArchive}
            totalAgents={totalCount}
            searchQuery={searchQuery}
            showInactive={showInactive}
            onClearSearch={() => setSearchQuery("")}
            onShowActiveOnly={() => setShowInactive(true)}
          />
        )}
        </div>
      </main>
    </div>
  );
}
