"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import {
  Shield,
  Users,
  Target,
  AlertTriangle,
  Clock,
  RefreshCw,
  Power,
  PowerOff,
} from "lucide-react";

// Types
interface ClientControl {
  client_name: string;
  enabled: boolean;
  disabled_at: string | null;
  disabled_by: string | null;
  reason: string | null;
  created_at: string;
  updated_at: string;
}

interface PurposeControl {
  purpose: string;
  enabled: boolean;
  disabled_at: string | null;
  disabled_by: string | null;
  reason: string | null;
  created_at: string;
  updated_at: string;
}

interface BlockedRequest {
  timestamp: string;
  client_name: string | null;
  purpose: string | null;
  source_path: string | null;
  block_reason: string;
  endpoint: string;
}

// API functions
async function fetchClients(): Promise<ClientControl[]> {
  const res = await fetch("/api/admin/clients");
  const data = await res.json();
  return data.clients || [];
}

async function fetchPurposes(): Promise<PurposeControl[]> {
  const res = await fetch("/api/admin/purposes");
  const data = await res.json();
  return data.purposes || [];
}

async function fetchBlockedRequests(): Promise<BlockedRequest[]> {
  const res = await fetch("/api/admin/blocked-requests?limit=50");
  const data = await res.json();
  return data.requests || [];
}

async function disableClient(
  clientName: string,
  reason: string,
  disabledBy: string
): Promise<void> {
  await fetch(`/api/admin/clients/${clientName}/disable`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason, disabled_by: disabledBy }),
  });
}

async function enableClient(clientName: string): Promise<void> {
  await fetch(`/api/admin/clients/${clientName}/disable`, {
    method: "DELETE",
  });
}

async function disablePurpose(
  purpose: string,
  reason: string,
  disabledBy: string
): Promise<void> {
  await fetch(`/api/admin/purposes/${purpose}/disable`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason, disabled_by: disabledBy }),
  });
}

async function enablePurpose(purpose: string): Promise<void> {
  await fetch(`/api/admin/purposes/${purpose}/disable`, {
    method: "DELETE",
  });
}

// Hold to confirm hook
function useHoldToConfirm(
  onConfirm: () => void,
  holdDuration: number = 1000
) {
  const [isHolding, setIsHolding] = useState(false);
  const [progress, setProgress] = useState(0);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const startTimeRef = useRef<number>(0);

  const start = useCallback(() => {
    setIsHolding(true);
    startTimeRef.current = Date.now();
    intervalRef.current = setInterval(() => {
      const elapsed = Date.now() - startTimeRef.current;
      const newProgress = Math.min((elapsed / holdDuration) * 100, 100);
      setProgress(newProgress);
      if (newProgress >= 100) {
        if (intervalRef.current) clearInterval(intervalRef.current);
        onConfirm();
        setIsHolding(false);
        setProgress(0);
      }
    }, 16);
  }, [holdDuration, onConfirm]);

  const cancel = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    setIsHolding(false);
    setProgress(0);
  }, []);

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  return { isHolding, progress, start, cancel };
}

// Toggle control component
function KillSwitchToggle({
  name,
  enabled,
  disabledAt,
  disabledBy,
  reason,
  onToggle,
  type,
}: {
  name: string;
  enabled: boolean;
  disabledAt: string | null;
  disabledBy: string | null;
  reason: string | null;
  onToggle: (reason: string) => void;
  type: "client" | "purpose";
}) {
  const [auditNote, setAuditNote] = useState("");
  const [showInput, setShowInput] = useState(false);

  const { isHolding, progress, start, cancel } = useHoldToConfirm(() => {
    if (!enabled || auditNote.trim()) {
      onToggle(auditNote);
      setAuditNote("");
      setShowInput(false);
    }
  });

  const handleClick = () => {
    if (enabled) {
      // Disabling - require audit note
      setShowInput(true);
    } else {
      // Enabling - start hold immediately
      start();
    }
  };

  return (
    <div
      className={`group relative p-4 rounded-xl border transition-all duration-200 ${
        enabled
          ? "bg-slate-900/30 border-slate-800 hover:border-slate-700"
          : "bg-red-950/30 border-red-900/50 hover:border-red-800"
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className={`p-2 rounded-lg ${
              enabled
                ? "bg-emerald-900/30 text-emerald-400"
                : "bg-red-900/30 text-red-400"
            }`}
          >
            {type === "client" ? (
              <Users className="w-4 h-4" />
            ) : (
              <Target className="w-4 h-4" />
            )}
          </div>
          <div>
            <h3 className="font-medium text-slate-100">{name}</h3>
            {!enabled && disabledAt && (
              <p className="text-xs text-slate-500">
                Disabled {new Date(disabledAt).toLocaleDateString()}
                {disabledBy && ` by ${disabledBy}`}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {!enabled && reason && (
            <span className="text-xs text-red-400 max-w-[200px] truncate">
              {reason}
            </span>
          )}

          <button
            onClick={handleClick}
            onMouseDown={!enabled ? start : undefined}
            onMouseUp={!enabled ? cancel : undefined}
            onMouseLeave={!enabled ? cancel : undefined}
            className={`relative overflow-hidden px-4 py-2 rounded-lg font-medium text-sm transition-all ${
              enabled
                ? "bg-red-600/20 text-red-400 hover:bg-red-600/30"
                : "bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600/30"
            }`}
          >
            {/* Progress bar for hold-to-confirm */}
            {isHolding && (
              <div
                className="absolute inset-0 bg-current opacity-20"
                style={{ width: `${progress}%` }}
              />
            )}
            <span className="relative flex items-center gap-2">
              {enabled ? (
                <>
                  <PowerOff className="w-4 h-4" />
                  Hold to Disable
                </>
              ) : (
                <>
                  <Power className="w-4 h-4" />
                  Hold to Enable
                </>
              )}
            </span>
          </button>
        </div>
      </div>

      {/* Audit note input for disabling */}
      {showInput && enabled && (
        <div className="mt-4 pt-4 border-t border-slate-800">
          <label className="block text-sm text-slate-400 mb-2">
            Audit note (required)
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={auditNote}
              onChange={(e) => setAuditNote(e.target.value)}
              placeholder="Reason for disabling..."
              className="flex-1 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-red-500/50"
            />
            <button
              disabled={!auditNote.trim()}
              onMouseDown={auditNote.trim() ? start : undefined}
              onMouseUp={cancel}
              onMouseLeave={cancel}
              className={`relative overflow-hidden px-4 py-2 rounded-lg font-medium text-sm transition-all ${
                auditNote.trim()
                  ? "bg-red-600 text-white hover:bg-red-500"
                  : "bg-slate-700 text-slate-500 cursor-not-allowed"
              }`}
            >
              {isHolding && (
                <div
                  className="absolute inset-0 bg-white opacity-20"
                  style={{ width: `${progress}%` }}
                />
              )}
              <span className="relative">Hold to Confirm</span>
            </button>
            <button
              onClick={() => {
                setShowInput(false);
                setAuditNote("");
              }}
              className="px-3 py-2 rounded-lg bg-slate-800 text-slate-400 hover:bg-slate-700"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Blocked requests log component
function BlockedRequestsLog({
  requests,
  isLoading,
}: {
  requests: BlockedRequest[];
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="animate-pulse space-y-3">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-12 bg-slate-800/50 rounded-lg" />
        ))}
      </div>
    );
  }

  if (requests.length === 0) {
    return (
      <div className="text-center py-12 text-slate-500">
        <Shield className="w-12 h-12 mx-auto mb-3 opacity-50" />
        <p>No blocked requests</p>
      </div>
    );
  }

  return (
    <div className="space-y-2 max-h-[400px] overflow-y-auto">
      {requests.map((req, idx) => (
        <div
          key={idx}
          className="flex items-center gap-3 p-3 rounded-lg bg-slate-900/30 border border-slate-800"
        >
          <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 text-sm">
              <span className="font-medium text-red-400">
                {req.client_name || "Unknown"}
              </span>
              {req.purpose && (
                <>
                  <span className="text-slate-600">/</span>
                  <span className="text-slate-400">{req.purpose}</span>
                </>
              )}
            </div>
            <div className="text-xs text-slate-500 truncate">
              {req.endpoint} - {req.block_reason}
            </div>
          </div>
          <div className="flex items-center gap-1 text-xs text-slate-600">
            <Clock className="w-3 h-3" />
            {new Date(req.timestamp).toLocaleTimeString()}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function AdminPage() {
  const [clients, setClients] = useState<ClientControl[]>([]);
  const [purposes, setPurposes] = useState<PurposeControl[]>([]);
  const [blockedRequests, setBlockedRequests] = useState<BlockedRequest[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const [c, p, b] = await Promise.all([
        fetchClients(),
        fetchPurposes(),
        fetchBlockedRequests(),
      ]);
      setClients(c);
      setPurposes(p);
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
    // Auto-refresh every 30 seconds
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

  const handleTogglePurpose = useCallback(
    async (purpose: string, enabled: boolean, reason: string) => {
      try {
        if (enabled) {
          await disablePurpose(purpose, reason, "admin");
        } else {
          await enablePurpose(purpose);
        }
        await refresh();
      } catch (error) {
        console.error("Failed to toggle purpose:", error);
      }
    },
    [refresh]
  );

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/80 backdrop-blur-lg">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-amber-900/30">
                <Shield className="w-5 h-5 text-amber-400" />
              </div>
              <h1 className="text-lg font-semibold text-slate-100">
                Admin - Usage Control
              </h1>
            </div>
            <button
              onClick={refresh}
              disabled={isRefreshing}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors"
            >
              <RefreshCw
                className={`w-4 h-4 ${isRefreshing ? "animate-spin" : ""}`}
              />
              Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-8 space-y-8">
        {/* Stats Summary */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="p-4 rounded-xl bg-slate-900/30 border border-slate-800">
            <div className="text-sm text-slate-500">Total Clients</div>
            <div className="text-2xl font-semibold text-slate-100">
              {clients.length}
            </div>
          </div>
          <div className="p-4 rounded-xl bg-slate-900/30 border border-slate-800">
            <div className="text-sm text-slate-500">Disabled Clients</div>
            <div className="text-2xl font-semibold text-red-400">
              {clients.filter((c) => !c.enabled).length}
            </div>
          </div>
          <div className="p-4 rounded-xl bg-slate-900/30 border border-slate-800">
            <div className="text-sm text-slate-500">Total Purposes</div>
            <div className="text-2xl font-semibold text-slate-100">
              {purposes.length}
            </div>
          </div>
          <div className="p-4 rounded-xl bg-slate-900/30 border border-slate-800">
            <div className="text-sm text-slate-500">Blocked Today</div>
            <div className="text-2xl font-semibold text-amber-400">
              {
                blockedRequests.filter(
                  (r) =>
                    new Date(r.timestamp).toDateString() ===
                    new Date().toDateString()
                ).length
              }
            </div>
          </div>
        </div>

        {/* Two-column layout */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Clients Section */}
          <section>
            <h2 className="text-lg font-medium text-slate-200 mb-4 flex items-center gap-2">
              <Users className="w-5 h-5 text-emerald-400" />
              Client Kill Switches
            </h2>
            <div className="space-y-3">
              {isLoading ? (
                <div className="animate-pulse space-y-3">
                  {[...Array(3)].map((_, i) => (
                    <div key={i} className="h-16 bg-slate-800/50 rounded-xl" />
                  ))}
                </div>
              ) : clients.length === 0 ? (
                <div className="text-center py-8 text-slate-500">
                  No clients registered yet
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
                    onToggle={(reason) =>
                      handleToggleClient(
                        client.client_name,
                        client.enabled,
                        reason
                      )
                    }
                    type="client"
                  />
                ))
              )}
            </div>
          </section>

          {/* Purposes Section */}
          <section>
            <h2 className="text-lg font-medium text-slate-200 mb-4 flex items-center gap-2">
              <Target className="w-5 h-5 text-blue-400" />
              Purpose Kill Switches
            </h2>
            <div className="space-y-3">
              {isLoading ? (
                <div className="animate-pulse space-y-3">
                  {[...Array(3)].map((_, i) => (
                    <div key={i} className="h-16 bg-slate-800/50 rounded-xl" />
                  ))}
                </div>
              ) : purposes.length === 0 ? (
                <div className="text-center py-8 text-slate-500">
                  No purposes registered yet
                </div>
              ) : (
                purposes.map((purpose) => (
                  <KillSwitchToggle
                    key={purpose.purpose}
                    name={purpose.purpose}
                    enabled={purpose.enabled}
                    disabledAt={purpose.disabled_at}
                    disabledBy={purpose.disabled_by}
                    reason={purpose.reason}
                    onToggle={(reason) =>
                      handleTogglePurpose(purpose.purpose, purpose.enabled, reason)
                    }
                    type="purpose"
                  />
                ))
              )}
            </div>
          </section>
        </div>

        {/* Blocked Requests Log */}
        <section>
          <h2 className="text-lg font-medium text-slate-200 mb-4 flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-amber-400" />
            Recent Blocked Requests
          </h2>
          <div className="p-4 rounded-xl bg-slate-900/30 border border-slate-800">
            <BlockedRequestsLog requests={blockedRequests} isLoading={isLoading} />
          </div>
        </section>
      </main>
    </div>
  );
}
