"use client";

import { useQuery } from "@tanstack/react-query";
import { Users, Plus, Shield, Ban, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { buildApiUrl } from "@/lib/api-config";

interface ClientResponse {
  client_id: string;
  display_name: string;
  secret_prefix: string;
  client_type: string;
  status: string;
  rate_limit_rpm: number;
  rate_limit_tpm: number;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
}

interface ClientListResponse {
  clients: ClientResponse[];
  total: number;
}

async function fetchClients(): Promise<ClientListResponse> {
  const response = await fetch(buildApiUrl("/access-control/clients"), {
    headers: {
      "X-Agent-Hub-Internal": "agent-hub-internal-v1",
    },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch clients: ${response.statusText}`);
  }
  return response.json();
}

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "Never";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export default function ClientsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["access-control-clients"],
    queryFn: fetchClients,
    refetchInterval: 30000,
  });

  const statusConfig = {
    active: { color: "text-emerald-400", bg: "bg-emerald-500/10", label: "Active" },
    suspended: { color: "text-amber-400", bg: "bg-amber-500/10", label: "Suspended" },
    blocked: { color: "text-red-400", bg: "bg-red-500/10", label: "Blocked" },
  };

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Users className="h-5 w-5 text-slate-400" />
            <h1 className="text-base font-semibold text-slate-100">Clients</h1>
            {data && (
              <span className="text-xs text-slate-500">({data.total})</span>
            )}
          </div>
          <a
            href="/access-control/clients/new"
            className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors"
          >
            <Plus className="h-4 w-4" />
            New Client
          </a>
        </div>
      </header>

      <main className="relative px-6 lg:px-8 py-6">
        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-900/20 border border-red-800/50">
            <p className="text-sm text-red-400">Failed to load clients</p>
          </div>
        )}

        {isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 bg-slate-800 rounded animate-pulse" />
            ))}
          </div>
        ) : data?.clients.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-400">
            <Users className="h-12 w-12 mb-4 opacity-50" />
            <p className="text-lg mb-2">No clients registered</p>
            <a
              href="/access-control/clients/new"
              className="text-blue-400 hover:text-blue-300"
            >
              Register your first client
            </a>
          </div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-800/80">
            <table className="w-full">
              <thead className="bg-slate-800/50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Client
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Type
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Last Used
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Rate Limits
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {data?.clients.map((client) => {
                  const config = statusConfig[client.status as keyof typeof statusConfig] || statusConfig.active;
                  return (
                    <tr
                      key={client.client_id}
                      className="hover:bg-slate-800/30 cursor-pointer"
                      onClick={() => window.location.href = `/access-control/clients/${client.client_id}`}
                    >
                      <td className="px-4 py-3">
                        <div>
                          <p className="text-sm font-medium text-slate-100">
                            {client.display_name}
                          </p>
                          <p className="text-xs text-slate-500 font-mono">
                            {client.secret_prefix}...
                          </p>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs px-2 py-1 rounded bg-slate-800 text-slate-300 capitalize">
                          {client.client_type}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={cn("text-xs px-2 py-1 rounded", config.bg, config.color)}>
                          {config.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-400">
                        {formatRelativeTime(client.last_used_at)}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500 font-mono">
                        {client.rate_limit_rpm} rpm / {(client.rate_limit_tpm / 1000).toFixed(0)}k tpm
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
