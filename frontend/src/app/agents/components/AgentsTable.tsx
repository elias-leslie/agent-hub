import { Bot } from "lucide-react";
import { AgentsTableHeader } from "./AgentsTableHeader";
import { AgentRow } from "./AgentRow";
import type { Agent, AgentMetrics, SortField, SortDirection } from "../lib/types";

export function AgentsTable({
  agents,
  sortField,
  sortDirection,
  onSort,
  getMetrics,
  onClone,
  onArchive,
  totalAgents,
  searchQuery,
  showInactive,
  onClearSearch,
  onShowActiveOnly,
}: {
  agents: Agent[];
  sortField: SortField;
  sortDirection: SortDirection;
  onSort: (field: SortField) => void;
  getMetrics: (slug: string) => AgentMetrics | null;
  onClone: (agent: Agent) => void;
  onArchive: (agent: Agent) => void;
  totalAgents: number;
  searchQuery: string;
  showInactive: boolean;
  onClearSearch: () => void;
  onShowActiveOnly: () => void;
}) {
  if (agents.length === 0) {
    const hasSearch = searchQuery.trim().length > 0;

    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white px-6 py-16 text-center dark:border-slate-700 dark:bg-slate-900">
        <Bot className="mx-auto mb-4 h-10 w-10 text-slate-600" />
        <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          {hasSearch ? `No agents match "${searchQuery.trim()}"` : "No agents to show"}
        </p>
        <p className="mx-auto mt-2 max-w-md text-sm text-slate-400">
          {hasSearch
            ? "Try a different name, slug, or description search."
            : showInactive
              ? "Only the persona agent is configured right now, or the current list is empty."
              : "Inactive agents are hidden by default, and the persona agent is managed from Persona Settings."}
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          {hasSearch && (
            <button
              type="button"
              onClick={onClearSearch}
              className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              Clear search
            </button>
          )}
          {!showInactive && totalAgents > 0 && (
            <button
              type="button"
              onClick={onShowActiveOnly}
              className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              Include inactive agents
            </button>
          )}
          <a
            href="/agents/new"
            className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-500"
          >
            New Agent
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 overflow-hidden shadow-sm overflow-x-auto">
      <AgentsTableHeader
        sortField={sortField}
        sortDirection={sortDirection}
        onSort={onSort}
      />
      <div className="divide-y divide-slate-100 dark:divide-slate-800/50 min-w-[940px]">
        {agents.map((agent) => (
          <AgentRow
            key={agent.id}
            agent={agent}
            metrics={getMetrics(agent.slug)}
            onClone={onClone}
            onArchive={onArchive}
          />
        ))}
      </div>
    </div>
  );
}
