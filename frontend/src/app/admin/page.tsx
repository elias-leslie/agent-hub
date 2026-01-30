"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import {
  Shield,
  Users,
  AlertTriangle,
  RefreshCw,
  PowerOff,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchClients,
  fetchBlockedRequests,
  disableClient,
  enableClient,
  type ClientControl,
  type BlockedRequest,
} from "./api";
import { KillSwitchToggle } from "./components/KillSwitchToggle";
import { BlockedRequestsTable } from "./components/BlockedRequestsTable";

export default function AdminPage() {
  const [clients, setClients] = useState<ClientControl[]>([]);
  const [blockedRequests, setBlockedRequests] = useState<BlockedRequest[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const [c, b] = await Promise.all([fetchClients(), fetchBlockedRequests()]);
      setClients(c);
      setBlockedRequests(b);
    } catch (error) {
      console.error("Failed to refresh:", error);
    } finally {
      setIsRefreshing(false);
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, [refresh]);

  const handleToggleClient = useCallback(
    async (clientName: string, enabled: boolean, reason: string) => {
      try {
        if (enabled) {
          await disableClient(clientName, reason, "admin");
        } else {
          await enableClient(clientName);
        }
        await refresh();
      } catch (error) {
        console.error("Failed to toggle client:", error);
      }
    },
    [refresh]
  );

  const todayBlocked = useMemo(() => {
    const today = new Date().toDateString();
    return blockedRequests.filter((r) => new Date(r.timestamp).toDateString() === today).length;
  }, [blockedRequests]);

  const unknownAttempts = useMemo(() => {
    return blockedRequests.filter((r) => r.client_name === "<unknown>").length;
  }, [blockedRequests]);

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Subtle grid pattern overlay */}
      <div
        className="fixed inset-0 pointer-events-none opacity-[0.015]"
        style={{
          backgroundImage: `linear-gradient(rgba(251,191,36,0.5) 1px, transparent 1px),
                            linear-gradient(90deg, rgba(251,191,36,0.5) 1px, transparent 1px)`,
          backgroundSize: "64px 64px",
        }}
      />

      {/* Header */}
      <header className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-4">
              <div className="p-2.5 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-600/20 border border-amber-500/30">
                <Shield className="w-6 h-6 text-amber-400" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-slate-100 tracking-tight">Usage Control</h1>
                <p className="text-xs text-slate-500">Kill switch administration</p>
              </div>
            </div>

            <div className="flex items-center gap-4">
              {/* Live indicator */}
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-950/50 border border-emerald-800/50">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                </span>
                <span className="text-xs font-medium text-emerald-400">Live</span>
              </div>

              <button
                onClick={refresh}
                disabled={isRefreshing}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors border border-slate-700"
              >
                <RefreshCw className={cn("w-4 h-4", isRefreshing && "animate-spin")} />
                Refresh
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-8 space-y-8 relative">
        {/* Stats Summary */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="p-5 rounded-xl bg-gradient-to-br from-slate-900/80 to-slate-900/40 border border-slate-800 hover:border-slate-700 transition-colors">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 rounded-lg bg-emerald-900/30">
                <Users className="w-4 h-4 text-emerald-400" />
              </div>
              <span className="text-sm text-slate-400">Total Clients</span>
            </div>
            <div className="text-3xl font-bold text-slate-100 tabular-nums">{clients.length}</div>
          </div>

          <div className="p-5 rounded-xl bg-gradient-to-br from-slate-900/80 to-slate-900/40 border border-slate-800 hover:border-slate-700 transition-colors">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 rounded-lg bg-red-900/30">
                <PowerOff className="w-4 h-4 text-red-400" />
              </div>
              <span className="text-sm text-slate-400">Disabled Clients</span>
            </div>
            <div className="text-3xl font-bold text-red-400 tabular-nums">
              {clients.filter((c) => !c.enabled).length}
            </div>
          </div>

          <div className="p-5 rounded-xl bg-gradient-to-br from-amber-950/50 to-slate-900/40 border border-amber-800/50 hover:border-amber-700 transition-colors">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 rounded-lg bg-amber-900/30">
                <Zap className="w-4 h-4 text-amber-400" />
              </div>
              <span className="text-sm text-amber-400/80">Blocked Today</span>
            </div>
            <div className="text-3xl font-bold text-amber-400 tabular-nums">{todayBlocked}</div>
          </div>

          <div className={cn(
            "p-5 rounded-xl border transition-colors",
            unknownAttempts > 0
              ? "bg-gradient-to-br from-red-950/50 to-slate-900/40 border-red-800/50 hover:border-red-700"
              : "bg-gradient-to-br from-slate-900/80 to-slate-900/40 border-slate-800 hover:border-slate-700"
          )}>
            <div className="flex items-center gap-3 mb-3">
              <div className={cn(
                "p-2 rounded-lg",
                unknownAttempts > 0 ? "bg-red-900/30" : "bg-slate-800"
              )}>
                <AlertTriangle className={cn(
                  "w-4 h-4",
                  unknownAttempts > 0 ? "text-red-400" : "text-slate-500"
                )} />
              </div>
              <span className={cn(
                "text-sm",
                unknownAttempts > 0 ? "text-red-400/80" : "text-slate-400"
              )}>Unknown Clients</span>
            </div>
            <div className={cn(
              "text-3xl font-bold tabular-nums",
              unknownAttempts > 0 ? "text-red-400" : "text-slate-500"
            )}>{unknownAttempts}</div>
          </div>
        </div>

        {/* Client Kill Switches Section */}
        <section>
          <div className="flex items-center gap-3 mb-4">
            <Users className="w-5 h-5 text-emerald-400" />
            <h2 className="text-lg font-semibold text-slate-100">Client Kill Switches</h2>
            <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
              {clients.length} registered
            </span>
          </div>
          <div className="space-y-3">
            {isLoading ? (
              <div className="animate-pulse space-y-3">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-16 bg-slate-800/50 rounded-xl" />
                ))}
              </div>
            ) : clients.length === 0 ? (
              <div className="text-center py-12 rounded-xl border border-dashed border-slate-800">
                <Users className="w-8 h-8 text-slate-700 mx-auto mb-2" />
                <p className="text-slate-500">No clients registered yet</p>
                <p className="text-xs text-slate-600 mt-1">Clients auto-register on first API call</p>
              </div>
            ) : (
              clients.map((client) => (
                <KillSwitchToggle
                  key={client.client_name}
                  name={client.client_name}
                  enabled={client.enabled}
                  disabledAt={client.disabled_at}
                  disabledBy={client.disabled_by}
                  reason={client.reason}
                  onToggle={(reason) => handleToggleClient(client.client_name, client.enabled, reason)}
                  type="client"
                />
              ))
            )}
          </div>
        </section>

        {/* Blocked Requests Section - Full Width */}
        <section>
          <div className="flex items-center gap-3 mb-4">
            <AlertTriangle className="w-5 h-5 text-amber-400" />
            <h2 className="text-lg font-semibold text-slate-100">Blocked Requests</h2>
            <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
              {blockedRequests.length} total
            </span>
          </div>
          <BlockedRequestsTable
            requests={blockedRequests}
            isLoading={isLoading}
            onRefresh={refresh}
            isRefreshing={isRefreshing}
          />
        </section>
      </main>
    </div>
  );
}
