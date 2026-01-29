import { Activity, Clock, CheckCircle2 } from "lucide-react";
import { SortableHeader } from "./SortableHeader";
import type { SortField, SortDirection } from "../lib/types";

export function AgentsTableHeader({
  sortField,
  sortDirection,
  onSort,
}: {
  sortField: SortField;
  sortDirection: SortDirection;
  onSort: (field: SortField) => void;
}) {
  return (
    <div className="bg-slate-50/95 dark:bg-slate-800/95 border-b border-slate-200 dark:border-slate-700 min-w-[1100px]">
      <div className="grid grid-cols-[180px_1fr_130px_130px_130px_130px_80px_40px] gap-3 px-4 py-2.5 items-center">
        <SortableHeader label="Agent" field="name" currentField={sortField} direction={sortDirection} onSort={onSort} />
        <SortableHeader label="Model" field="model" currentField={sortField} direction={sortDirection} onSort={onSort} />
        <SortableHeader label="Status" field="status" currentField={sortField} direction={sortDirection} onSort={onSort} />
        <SortableHeader
          label="Requests 24h"
          field="requests"
          currentField={sortField}
          direction={sortDirection}
          onSort={onSort}
          icon={<Activity className="h-3 w-3" />}
        />
        <SortableHeader
          label="Latency"
          field="latency"
          currentField={sortField}
          direction={sortDirection}
          onSort={onSort}
          icon={<Clock className="h-3 w-3" />}
        />
        <SortableHeader
          label="Success"
          field="success"
          currentField={sortField}
          direction={sortDirection}
          onSort={onSort}
          icon={<CheckCircle2 className="h-3 w-3" />}
        />
        <SortableHeader label="Ver" field="version" currentField={sortField} direction={sortDirection} onSort={onSort} align="right" />
        <div />
      </div>
    </div>
  );
}
