import { useRef, useCallback } from "react";
import { Bot } from "lucide-react";
import { RequestLogEntry, SortField, SortDirection } from "../types";
import { formatTime, formatLatency, formatNumber } from "../utils";
import { SortableHeader } from "./SortableHeader";
import { ToolTypeBadge, StatusBadge } from "./Badges";

interface RequestTableProps {
  requests: RequestLogEntry[];
  total: number;
  sortField: SortField;
  sortDirection: SortDirection;
  onSort: (field: SortField) => void;
  isFetchingNextPage: boolean;
  hasNextPage: boolean | undefined;
  onFetchNextPage: () => void;
}

export function RequestTable({
  requests,
  total,
  sortField,
  sortDirection,
  onSort,
  isFetchingNextPage,
  hasNextPage,
  onFetchNextPage,
}: RequestTableProps) {
  const tableRef = useRef<HTMLDivElement>(null);

  const handleScroll = useCallback(() => {
    if (!tableRef.current || isFetchingNextPage || !hasNextPage) return;
    const { scrollTop, scrollHeight, clientHeight } = tableRef.current;
    if (scrollHeight - scrollTop - clientHeight < 500) {
      onFetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, onFetchNextPage]);

  return (
    <div
      ref={tableRef}
      onScroll={handleScroll}
      className="overflow-auto rounded-xl border border-slate-800/80 max-h-[calc(100vh-420px)]"
    >
      <table className="w-full min-w-[1200px]">
        <thead className="bg-slate-800/50 sticky top-0 z-10">
          <tr>
            <th className="text-left">
              <SortableHeader label="Time" field="time" currentField={sortField} direction={sortDirection} onSort={onSort} />
            </th>
            <th className="text-left">
              <SortableHeader label="Type" field="type" currentField={sortField} direction={sortDirection} onSort={onSort} />
            </th>
            <th className="text-left">
              <SortableHeader label="Tool" field="tool" currentField={sortField} direction={sortDirection} onSort={onSort} />
            </th>
            <th className="text-left">
              <SortableHeader label="Agent" field="agent" currentField={sortField} direction={sortDirection} onSort={onSort} />
            </th>
            <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Client
            </th>
            <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Endpoint
            </th>
            <th className="text-left">
              <SortableHeader label="Status" field="status" currentField={sortField} direction={sortDirection} onSort={onSort} />
            </th>
            <th className="text-left">
              <SortableHeader label="Latency" field="latency" currentField={sortField} direction={sortDirection} onSort={onSort} />
            </th>
            <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Reason
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/50">
          {requests.map((req) => (
            <tr key={req.id} className="hover:bg-slate-800/30 transition-colors">
              <td className="px-4 py-3 text-xs text-slate-400 font-mono whitespace-nowrap">
                {formatTime(req.created_at)}
              </td>
              <td className="px-4 py-3">
                <ToolTypeBadge type={req.tool_type} />
              </td>
              <td className="px-4 py-3">
                {req.tool_name ? (
                  <span className="text-sm font-mono text-slate-300">
                    {req.tool_name}
                  </span>
                ) : (
                  <span className="text-sm text-slate-500">-</span>
                )}
              </td>
              <td className="px-4 py-3">
                {req.agent_slug ? (
                  <span className="inline-flex items-center gap-1.5 text-sm text-amber-400 font-medium">
                    <Bot className="h-3.5 w-3.5" />
                    {req.agent_slug}
                  </span>
                ) : (
                  <span className="text-sm text-slate-500">-</span>
                )}
              </td>
              <td className="px-4 py-3">
                <div>
                  <p className="text-sm text-slate-100">
                    {req.client_display_name || "Unknown"}
                  </p>
                  {req.request_source && (
                    <p className="text-xs text-slate-500">{req.request_source}</p>
                  )}
                </div>
              </td>
              <td className="px-4 py-3">
                <span className="text-xs font-mono text-slate-500 mr-2">{req.method}</span>
                <span className="text-sm text-slate-100 font-mono">{req.endpoint}</span>
              </td>
              <td className="px-4 py-3">
                <StatusBadge code={req.status_code} />
              </td>
              <td className="px-4 py-3 text-sm text-slate-400 font-mono">
                {formatLatency(req.latency_ms)}
              </td>
              <td className="px-4 py-3 text-sm text-amber-400 max-w-xs truncate">
                {req.rejection_reason || "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Infinite scroll loading indicator */}
      {isFetchingNextPage && (
        <div className="flex items-center justify-center py-4 bg-slate-900/50">
          <div className="flex items-center gap-2 text-slate-400 text-sm">
            <div className="w-4 h-4 border-2 border-slate-500 border-t-transparent rounded-full animate-spin" />
            Loading more...
          </div>
        </div>
      )}

      {/* End of list indicator */}
      {!hasNextPage && requests.length > 0 && (
        <div className="flex items-center justify-center py-3 text-xs text-slate-500 bg-slate-900/30">
          Showing all {formatNumber(requests.length)} of {formatNumber(total)} requests
        </div>
      )}
    </div>
  );
}
