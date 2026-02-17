import { RefreshCw, MessageSquare } from "lucide-react";
import type { SessionListItem, Session, SessionEventsResponse } from "@/lib/api";
import { SortField, SortDirection } from "../types";
import { SortableHeader } from "@/components/ui/SortableHeader";
import { SessionTableRow } from "./SessionTableRow";

export function SessionTable({
  sessions,
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
    return (
      <div className="text-center py-20 text-slate-400">
        <MessageSquare className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="text-sm font-medium">
          {modelFilter ? `No sessions with model: ${modelFilter}` : "No sessions found"}
        </p>
      </div>
    );
  }

  return (
    <div
      ref={tableRef}
      tabIndex={0}
      onKeyDown={onKeyDown}
      onScroll={onScroll}
      className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 overflow-auto shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 max-h-[calc(100vh-280px)]"
    >
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
            onSort={onSort}
          />
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Agent
          </span>
          <SortableHeader
            label="Model"
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
          <div /> {/* Actions column */}
        </div>
      </div>

      {/* TABLE BODY */}
      <div className="divide-y divide-slate-100 dark:divide-slate-800/50">
        {sessions.map((session, index) => (
          <SessionTableRow
            key={session.id}
            session={session}
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
