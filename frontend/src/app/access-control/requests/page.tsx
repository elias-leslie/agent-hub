"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Clock, Filter, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { buildApiUrl, fetchApi } from "@/lib/api-config";

interface RequestLogEntry {
  id: number;
  client_id: string | null;
  client_display_name: string | null;
  request_source: string | null;
  endpoint: string;
  method: string;
  status_code: number;
  rejection_reason: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number | null;
  model: string | null;
  created_at: string;
}

interface RequestLogResponse {
  requests: RequestLogEntry[];
  total: number;
}

async function fetchRequestLog(params: {
  client_id?: string;
  status_code?: number;
  rejected_only?: boolean;
  limit?: number;
  offset?: number;
}): Promise<RequestLogResponse> {
  const searchParams = new URLSearchParams();
  if (params.client_id) searchParams.set("client_id", params.client_id);
  if (params.status_code) searchParams.set("status_code", params.status_code.toString());
  if (params.rejected_only) searchParams.set("rejected_only", "true");
  if (params.limit) searchParams.set("limit", params.limit.toString());
  if (params.offset) searchParams.set("offset", params.offset.toString());

  const response = await fetchApi(buildApiUrl(`/api/access-control/request-log?${searchParams.toString()}`));
  if (!response.ok) {
    throw new Error(`Failed to fetch request log: ${response.statusText}`);
  }
  return response.json();
}

function formatTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString();
}

function StatusBadge({ code }: { code: number }) {
  const config = code >= 500
    ? { color: "text-red-400", bg: "bg-red-500/10" }
    : code >= 400
    ? { color: "text-amber-400", bg: "bg-amber-500/10" }
    : { color: "text-emerald-400", bg: "bg-emerald-500/10" };

  return (
    <span className={cn("text-xs px-2 py-0.5 rounded font-mono", config.bg, config.color)}>
      {code}
    </span>
  );
}

export default function RequestLogPage() {
  const [clientFilter, setClientFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<number | undefined>();
  const [rejectedOnly, setRejectedOnly] = useState(false);
  const [page, setPage] = useState(0);
  const pageSize = 50;

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["request-log", clientFilter, statusFilter, rejectedOnly, page],
    queryFn: () => fetchRequestLog({
      client_id: clientFilter || undefined,
      status_code: statusFilter,
      rejected_only: rejectedOnly,
      limit: pageSize,
      offset: page * pageSize,
    }),
    refetchInterval: 10000,
  });

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Clock className="h-5 w-5 text-slate-400" />
            <h1 className="text-base font-semibold text-slate-100">Request Log</h1>
            {data && (
              <span className="text-xs text-slate-500">({data.total} total)</span>
            )}
          </div>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm transition-colors"
          >
            <RefreshCw className={cn("h-4 w-4", isFetching && "animate-spin")} />
            Refresh
          </button>
        </div>
      </header>

      <main className="relative px-6 lg:px-8 py-6">
        {/* Filters */}
        <div className="flex flex-wrap gap-3 mb-6">
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700">
            <Filter className="h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder="Filter by client ID..."
              value={clientFilter}
              onChange={(e) => { setClientFilter(e.target.value); setPage(0); }}
              className="bg-transparent border-none outline-none text-sm text-slate-100 placeholder-slate-500 w-48"
            />
          </div>

          <select
            value={statusFilter || ""}
            onChange={(e) => { setStatusFilter(e.target.value ? parseInt(e.target.value) : undefined); setPage(0); }}
            className="px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700 text-sm text-slate-100"
          >
            <option value="">All Status Codes</option>
            <option value="200">200 OK</option>
            <option value="400">400 Bad Request</option>
            <option value="403">403 Forbidden</option>
            <option value="500">500 Error</option>
          </select>

          <label className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700 cursor-pointer">
            <input
              type="checkbox"
              checked={rejectedOnly}
              onChange={(e) => { setRejectedOnly(e.target.checked); setPage(0); }}
              className="rounded bg-slate-700 border-slate-600"
            />
            <span className="text-sm text-slate-300">Rejected only</span>
          </label>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-900/20 border border-red-800/50">
            <p className="text-sm text-red-400">Failed to load request log</p>
          </div>
        )}

        {isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-12 bg-slate-800 rounded animate-pulse" />
            ))}
          </div>
        ) : data?.requests.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-400">
            <Clock className="h-12 w-12 mb-4 opacity-50" />
            <p className="text-lg">No requests found</p>
          </div>
        ) : (
          <>
            <div className="overflow-hidden rounded-lg border border-slate-800/80">
              <table className="w-full">
                <thead className="bg-slate-800/50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Time
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Client
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Endpoint
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Status
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Latency
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Reason
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {data?.requests.map((req) => (
                    <tr key={req.id} className="hover:bg-slate-800/30">
                      <td className="px-4 py-3 text-xs text-slate-400 font-mono">
                        {formatTime(req.created_at)}
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
                        <span className="text-xs font-mono text-slate-500 mr-2">
                          {req.method}
                        </span>
                        <span className="text-sm text-slate-100 font-mono">
                          {req.endpoint}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge code={req.status_code} />
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-400 font-mono">
                        {req.latency_ms ? `${req.latency_ms}ms` : "-"}
                      </td>
                      <td className="px-4 py-3 text-sm text-amber-400">
                        {req.rejection_reason || "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {data && data.total > pageSize && (
              <div className="flex items-center justify-between mt-4">
                <p className="text-sm text-slate-400">
                  Showing {page * pageSize + 1}-{Math.min((page + 1) * pageSize, data.total)} of {data.total}
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setPage(Math.max(0, page - 1))}
                    disabled={page === 0}
                    className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm disabled:opacity-50"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => setPage(page + 1)}
                    disabled={(page + 1) * pageSize >= data.total}
                    className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
