import { SortableHeader } from '@/components/ui/SortableHeader'
import type { Session, SessionEventsResponse, SessionListItem } from '@/lib/api'
import type { ModelCost } from '@/lib/models'
import type { SortDirection, SortField } from '../types'
import { SessionTableRow } from './SessionTableRow'

export function SessionTable({
  sessions,
  modelCosts,
  sortField,
  sortDirection,
  modelFilter,
  expandedSessionId,
  expandedSessionData,
  expandedEventsData,
  isLoadingDetails,
  liveSessionIds,
  focusedRowIndex,
  flashingSessionIds,
  tableRef,
  onSort,
  onKeyDown,
  onScroll,
  onToggleExpand,
  onModelFilterClick,
}: {
  sessions: SessionListItem[]
  modelCosts: Map<string, ModelCost>
  sortField: SortField
  sortDirection: SortDirection
  modelFilter: string
  expandedSessionId: string | null
  expandedSessionData: Session | null
  expandedEventsData: SessionEventsResponse | null
  isLoadingDetails: boolean
  liveSessionIds: Set<string>
  focusedRowIndex: number
  flashingSessionIds: Set<string>
  tableRef: React.RefObject<HTMLDivElement | null>
  onSort: (field: SortField) => void
  onKeyDown: (e: React.KeyboardEvent) => void
  onScroll: () => void
  onToggleExpand: (sessionId: string) => void
  onModelFilterClick: (model: string) => void
}) {
  if (sessions.length === 0) {
    return null
  }

  return (
    <div
      ref={tableRef}
      onKeyDown={onKeyDown}
      onScroll={onScroll}
      className="max-h-[calc(100vh-220px)] overflow-auto border border-slate-800/70 bg-slate-950/70 focus:outline-none focus:ring-2 focus:ring-amber-500/30"
    >
      <div className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-950/95 backdrop-blur-sm">
        <div className="grid grid-cols-[56px_minmax(120px,0.55fr)_minmax(280px,1.6fr)_minmax(360px,1.45fr)_72px_64px] items-center gap-3 px-4 py-2.5">
          <SortableHeader
            label="Status"
            field="status"
            currentField={sortField}
            direction={sortDirection}
            onSort={onSort}
          />
          <SortableHeader
            label="Project"
            field="project"
            currentField={sortField}
            direction={sortDirection}
            onSort={onSort}
          />
          <span className="text-[10px] font-mono uppercase tracking-[0.22em] text-slate-500">
            Description
          </span>
          <SortableHeader
            label="Agent"
            field="agent"
            currentField={sortField}
            direction={sortDirection}
            onSort={onSort}
          />
          <SortableHeader
            label="Time"
            field="time"
            currentField={sortField}
            direction={sortDirection}
            onSort={onSort}
            align="right"
          />
          <div className="text-right text-[10px] font-mono uppercase tracking-[0.22em] text-slate-500">
            Open
          </div>
        </div>
      </div>

      <div className="divide-y divide-slate-800/60">
        {sessions.map((session, index) => (
          <SessionTableRow
            key={session.id}
            session={session}
            modelCosts={modelCosts}
            isExpanded={expandedSessionId === session.id}
            isLive={liveSessionIds.has(session.id)}
            isFocused={focusedRowIndex === index}
            isFlashing={flashingSessionIds.has(session.id)}
            modelFilter={modelFilter}
            expandedSessionData={expandedSessionData}
            expandedEventsData={expandedEventsData}
            isLoadingDetails={isLoadingDetails}
            onToggleExpand={onToggleExpand}
            onModelFilterClick={onModelFilterClick}
          />
        ))}
      </div>
    </div>
  )
}
