"use client";

import { useQuery } from "@tanstack/react-query";
import { Shield, Users, Ban, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { buildApiUrl, fetchApi } from "@/lib/api-config";

interface ClientStatsResponse {
  total_clients: number;
  active_clients: number;
  suspended_clients: number;
  blocked_clients: number;
  blocked_requests_today: number;
  total_requests_today: number;
}

async function fetchAccessControlStats(): Promise<ClientStatsResponse> {
  const response = await fetchApi(buildApiUrl("/api/access-control/stats"));
  if (!response.ok) {
    throw new Error(`Failed to fetch stats: ${response.statusText}`);
  }
  return response.json();
}

function StatCard({
  label,
  value,
  subtext,
  icon: Icon,
  status = "neutral",
}: {
  label: string;
  value: string | number;
  subtext?: string;
  icon: React.ComponentType<{ className?: string }>;
  status?: "success" | "warning" | "error" | "neutral";
}) {
  const statusConfig = {
    success: {
      border: "border-l-emerald-500",
      dot: "bg-emerald-500",
    },
    warning: {
      border: "border-l-amber-500",
      dot: "bg-amber-500",
    },
    error: {
      border: "border-l-red-500",
      dot: "bg-red-500",
    },
    neutral: {
      border: "border-l-slate-600",
      dot: "bg-slate-400",
    },
  };

  const config = statusConfig[status];

  return (
    <div
      className={cn(
        "relative overflow-hidden",
        "bg-slate-900/60 backdrop-blur-sm",
        "border border-slate-800/80",
        "border-l-[3px]",
        config.border,
        "rounded-lg",
        "p-5"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
              {label}
            </span>
          </div>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-50 font-mono tabular-nums">
            {value}
          </p>
          {subtext && (
            <p className="mt-1 text-xs text-slate-400">
              {subtext}
            </p>
          )}
        </div>
        <div className="p-2 rounded-md bg-slate-800/80">
          <Icon className="h-5 w-5 text-slate-400" />
        </div>
      </div>
    </div>
  );
}

export default function AccessControlPage() {
  const { data: stats, isLoading, error } = useQuery({
    queryKey: ["access-control-stats"],
    queryFn: fetchAccessControlStats,
    refetchInterval: 30000,
  });

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Shield className="h-5 w-5 text-slate-400" />
            <h1 className="text-base font-semibold text-slate-100">
              Access Control
            </h1>
          </div>
        </div>
      </header>

      <main className="relative px-6 lg:px-8 py-6">
        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-900/20 border border-red-800/50">
            <p className="text-sm text-red-400">
              Unable to load access control statistics
            </p>
          </div>
        )}

        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-32 bg-slate-800 rounded animate-pulse" />
            ))}
          </div>
        ) : stats ? (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
              <StatCard
                label="Total Clients"
                value={stats.total_clients}
                icon={Users}
                status="neutral"
              />
              <StatCard
                label="Active Clients"
                value={stats.active_clients}
                icon={Shield}
                status="success"
              />
              <StatCard
                label="Blocked Requests"
                value={stats.blocked_requests_today}
                subtext="Today"
                icon={Ban}
                status={stats.blocked_requests_today > 0 ? "warning" : "success"}
              />
              <StatCard
                label="Total Requests"
                value={stats.total_requests_today}
                subtext="Today"
                icon={Clock}
                status="neutral"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <a
                href="/access-control/clients"
                className="block p-5 rounded-lg border border-slate-800/80 bg-slate-900/60 hover:bg-slate-900/80 transition-colors"
              >
                <div className="flex items-center gap-3 mb-2">
                  <Users className="h-5 w-5 text-blue-400" />
                  <h2 className="text-sm font-semibold text-slate-100">Clients</h2>
                </div>
                <p className="text-xs text-slate-400">
                  Manage registered clients and credentials
                </p>
              </a>

              <a
                href="/access-control/requests"
                className="block p-5 rounded-lg border border-slate-800/80 bg-slate-900/60 hover:bg-slate-900/80 transition-colors"
              >
                <div className="flex items-center gap-3 mb-2">
                  <Clock className="h-5 w-5 text-emerald-400" />
                  <h2 className="text-sm font-semibold text-slate-100">Request Log</h2>
                </div>
                <p className="text-xs text-slate-400">
                  View request history and attribution
                </p>
              </a>

              <a
                href="/access-control/clients/new"
                className="block p-5 rounded-lg border border-slate-800/80 bg-blue-900/20 hover:bg-blue-900/30 transition-colors"
              >
                <div className="flex items-center gap-3 mb-2">
                  <Shield className="h-5 w-5 text-blue-400" />
                  <h2 className="text-sm font-semibold text-slate-100">New Client</h2>
                </div>
                <p className="text-xs text-slate-400">
                  Register a new API client
                </p>
              </a>
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
