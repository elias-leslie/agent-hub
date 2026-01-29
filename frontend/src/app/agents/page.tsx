"use client";

import { useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  RefreshCw,
  Search,
  AlertCircle,
  Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchApi } from "@/lib/api-config";
import { GlobalInstructionsPanel } from "@/components/GlobalInstructionsPanel";
import { AgentsTable } from "./components/AgentsTable";
import { fetchAgents, fetchMetrics } from "./lib/api";
import { useAgentFiltering } from "./hooks/useAgentFiltering";
import type { Agent, AgentMetrics, SortField, SortDirection } from "./lib/types";

export default function AgentsPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [sortField, setSortField] = useState<SortField>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  const handleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortDirection(d => d === "desc" ? "asc" : "desc");
    } else {
      setSortField(field);
      setSortDirection("desc");
    }
  }, [sortField]);

  const { data, isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: ["agents", { activeOnly: !showInactive }],
    queryFn: () => fetchAgents(!showInactive),
  });

  const { data: metricsData } = useQuery({
    queryKey: ["agent-metrics"],
    queryFn: fetchMetrics,
    refetchInterval: 60000, // Refresh metrics every minute
  });

  const filteredAgents = useAgentFiltering({
    agents: data?.agents,
    searchQuery,
    sortField,
    sortDirection,
    metricsData: metricsData?.metrics,
  });

  const getMetrics = useCallback(
    (slug: string): AgentMetrics | null => {
      return metricsData?.metrics?.[slug] ?? null;
    },
    [metricsData]
  );

  const handleClone = useCallback((agent: Agent) => {
    // Navigate to create page with agent data pre-filled
    const params = new URLSearchParams({ clone: agent.slug });
    window.location.href = `/agents/new?${params}`;
  }, []);

  const handleArchive = useCallback(
    async (agent: Agent) => {
      if (!confirm(`Archive agent "${agent.name}"? This will deactivate it.`)) {
        return;
      }
      try {
        const res = await fetchApi(`/api/agents/${agent.slug}`, {
          method: "DELETE",
        });
        if (!res.ok) throw new Error("Failed to archive agent");
        refetch();
      } catch (err) {
        console.error("Archive failed:", err);
        alert("Failed to archive agent");
      }
    },
    [refetch]
  );

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

              {/* New Agent */}
              <a
                href="/agents/new"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
                New Agent
              </a>
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-5">
        {/* Global Instructions Panel */}
        <GlobalInstructionsPanel
          activeAgentCount={data?.agents?.filter((a) => a.is_active).length ?? 0}
        />

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
          <AgentsTable
            agents={filteredAgents}
            sortField={sortField}
            sortDirection={sortDirection}
            onSort={handleSort}
            getMetrics={getMetrics}
            onClone={handleClone}
            onArchive={handleArchive}
          />
        )}
      </main>
    </div>
  );
}
