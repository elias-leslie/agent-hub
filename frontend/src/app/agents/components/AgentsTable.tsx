import { Bot } from 'lucide-react'
import type {
  Agent,
  AgentMetrics,
  SortDirection,
  SortField,
} from '../lib/types'
import { AgentRow } from './AgentRow'
import { AgentsTableHeader } from './AgentsTableHeader'

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
  agents: Agent[]
  sortField: SortField
  sortDirection: SortDirection
  onSort: (field: SortField) => void
  getMetrics: (slug: string) => AgentMetrics | null
  onClone: (agent: Agent) => void
  onArchive: (agent: Agent) => void
  totalAgents: number
  searchQuery: string
  showInactive: boolean
  onClearSearch: () => void
  onShowActiveOnly: () => void
}) {
  if (agents.length === 0) {
    const hasSearch = searchQuery.trim().length > 0

    return (
      <div className="empty-surface">
        <Bot className="mx-auto mb-4 h-10 w-10 text-slate-600" />
        <p className="text-sm font-semibold text-slate-200">
          {hasSearch
            ? `No agents match "${searchQuery.trim()}"`
            : 'No agents to show'}
        </p>
        <p className="mx-auto mt-2 max-w-md text-sm text-slate-400">
          {hasSearch
            ? 'Try a different name, slug, or description search.'
            : showInactive
              ? 'Only the persona agent is configured right now, or the current list is empty.'
              : 'Inactive agents are hidden by default, and the persona agent is managed from Persona Settings.'}
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          {hasSearch && (
            <button
              type="button"
              onClick={onClearSearch}
              className="button-secondary px-3 py-2 text-xs"
            >
              Clear search
            </button>
          )}
          {!showInactive && totalAgents > 0 && (
            <button
              type="button"
              onClick={onShowActiveOnly}
              className="button-secondary px-3 py-2 text-xs"
            >
              Include inactive agents
            </button>
          )}
          <a href="/agents/new" className="button-primary px-3 py-2 text-xs">
            New Agent
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="table-surface overflow-x-auto">
      <AgentsTableHeader
        sortField={sortField}
        sortDirection={sortDirection}
        onSort={onSort}
      />
      <div className="divide-y divide-slate-800/50 min-w-[940px]">
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
  )
}
