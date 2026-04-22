import { SortableHeader } from "@/components/ui/SortableHeader";
import type { SessionListItem, Session, SessionEventsResponse } from "@/lib/api";
import type { ModelCost } from "@/lib/models";
import { SortField, SortDirection } from "../types";
import { SessionTableRow } from "./SessionTableRow";

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
  sessions: SessionListItem[];
  modelCosts: Map<string, ModelCost>;
  sortField: SortField;
  sortDirection: SortDirection;
  modelFilter: string;
  expandedSessionId: string | null;
  expandedSessionData: Session | null;
  expandedEventsData: SessionEventsResponse | null;
  isLoadingDetails: boolean;
  liveSessionIds: Set<string>;
  focusedRowIndex: number;
  flashingSessionIds: Set<string>;
  tableRef: React.RefObject<HTMLDivElement | null>;
  onSort: (field: SortField) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  onScroll: () => void;
  onToggleExpand: (sessionId: string) => void;
  onModelFilterClick: (model: string) => void;
}) {
  if (sessions.length === 0) {
    return null;
  }

  return (
    <div
      ref={tableRef}
      tabIndex={0}
      onKeyDown={onKeyDown}
      onScroll={onScroll}
      className="table-surface max-h-[calc(100vh-280px)] overflow-auto rounded-2xl border border-slate-800 bg-slate-950/85 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
    >
      <div className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/95 backdrop-blur-sm">
        <div className="grid grid-cols-[92px_minmax(220px,1.25fr)_minmax(170px,0.95fr)_minmax(240px,1.4fr)_110px_90px_90px_76px] items-center gap-3 px-5 py-3">
          <span className="text-[10px] font-mono uppercase tracking-[0.22em] text-slate-500">
            State
          </span>
          <SortableHeader
            label="Project"
            field="project"
            currentField={sortField}
            direction={sortDirection}
            onSort={onSort}
          />
          <span className="text-[10px] font-mono uppercase tracking-[0.22em] text-slate-500">
            Agent / counts
          </span>
          <SortableHeader
            label="Execution identity"
            field="model"
            currentField={sortField}
            direction={sortDirection}
            onSort={onSort}
          />
          <SortableHeader
            label="Tokens"
            field="tokens"
            currentField={sortField}
            direction={sortDirection}
            onSort={onSort}
            align="right"
          />
          <SortableHeader
            label="Cost"
            field="cost"
            currentField={sortField}
            direction={sortDirection}
            onSort={onSort}
            align="right"
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
            Actions
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
  );
}
