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
}: {
  agents: Agent[];
  sortField: SortField;
  sortDirection: SortDirection;
  onSort: (field: SortField) => void;
  getMetrics: (slug: string) => AgentMetrics | null;
  onClone: (agent: Agent) => void;
  onArchive: (agent: Agent) => void;
}) {
  if (agents.length === 0) {
    return (
      <div className="text-center py-20 text-slate-400">
        <Bot className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm font-medium">No agents found</p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm overflow-x-auto">
      <AgentsTableHeader
        sortField={sortField}
        sortDirection={sortDirection}
        onSort={onSort}
      />
      <div className="divide-y divide-slate-100 dark:divide-slate-800/50 min-w-[1100px]">
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
