"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Shield, ArrowLeft, Ban, Play, Trash2, RefreshCw, Copy, Check, Pencil } from "lucide-react";
import { cn } from "@/lib/utils";
import { buildApiUrl, fetchApi } from "@/lib/api-config";

interface ClientResponse {
  client_id: string;
  display_name: string;
  secret_prefix: string;
  client_type: string;
  status: string;
  rate_limit_rpm: number;
  rate_limit_tpm: number;
  allowed_projects: string[] | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  suspended_at: string | null;
  suspended_by: string | null;
  suspension_reason: string | null;
}

interface ClientUpdateRequest {
  display_name?: string;
  rate_limit_rpm?: number;
  rate_limit_tpm?: number;
  allowed_projects?: string[];
}

async function fetchClient(clientId: string): Promise<ClientResponse> {
  const response = await fetchApi(buildApiUrl(`/api/access-control/clients/${clientId}`), {
    headers: {
      "X-Agent-Hub-Internal": "agent-hub-internal-v1",
    },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch client: ${response.statusText}`);
  }
  return response.json();
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "Never";
  return new Date(dateStr).toLocaleString();
}

export default function ClientDetailPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const clientId = params.id as string;

  const [suspendReason, setSuspendReason] = useState("");
  const [showSuspendModal, setShowSuspendModal] = useState(false);
  const [showBlockModal, setShowBlockModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [newSecret, setNewSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Edit form state
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editRateLimitRpm, setEditRateLimitRpm] = useState(60);
  const [editRateLimitTpm, setEditRateLimitTpm] = useState(100000);
  const [editAllowedProjects, setEditAllowedProjects] = useState("");
  const [allowUnrestricted, setAllowUnrestricted] = useState(true);

  const { data: client, isLoading, error } = useQuery({
    queryKey: ["access-control-client", clientId],
    queryFn: () => fetchClient(clientId),
    refetchInterval: 10000,
  });

  const suspendMutation = useMutation({
    mutationFn: async (reason: string) => {
      const response = await fetch(buildApiUrl(`/access-control/clients/${clientId}/suspend`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Agent-Hub-Internal": "agent-hub-internal-v1",
        },
        body: JSON.stringify({ reason }),
      });
      if (!response.ok) throw new Error("Failed to suspend client");
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["access-control-client", clientId] });
      setShowSuspendModal(false);
      setSuspendReason("");
    },
  });

  const activateMutation = useMutation({
    mutationFn: async () => {
      const response = await fetch(buildApiUrl(`/access-control/clients/${clientId}/activate`), {
        method: "POST",
        headers: {
          "X-Agent-Hub-Internal": "agent-hub-internal-v1",
        },
      });
      if (!response.ok) throw new Error("Failed to activate client");
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["access-control-client", clientId] });
    },
  });

  const blockMutation = useMutation({
    mutationFn: async (reason: string) => {
      const response = await fetch(buildApiUrl(`/access-control/clients/${clientId}/block`), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Agent-Hub-Internal": "agent-hub-internal-v1",
        },
        body: JSON.stringify({ reason }),
      });
      if (!response.ok) throw new Error("Failed to block client");
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["access-control-client", clientId] });
      setShowBlockModal(false);
      setSuspendReason("");
    },
  });

  const rotateSecretMutation = useMutation({
    mutationFn: async () => {
      const response = await fetch(buildApiUrl(`/access-control/clients/${clientId}/rotate-secret`), {
        method: "POST",
        headers: {
          "X-Agent-Hub-Internal": "agent-hub-internal-v1",
        },
      });
      if (!response.ok) throw new Error("Failed to rotate secret");
      return response.json();
    },
    onSuccess: (data) => {
      setNewSecret(data.secret);
      queryClient.invalidateQueries({ queryKey: ["access-control-client", clientId] });
    },
  });

  const updateMutation = useMutation({
    mutationFn: async (data: ClientUpdateRequest) => {
      const response = await fetch(buildApiUrl(`/access-control/clients/${clientId}`), {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "X-Agent-Hub-Internal": "agent-hub-internal-v1",
        },
        body: JSON.stringify(data),
      });
      if (!response.ok) throw new Error("Failed to update client");
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["access-control-client", clientId] });
      setShowEditModal(false);
    },
  });

  function openEditModal() {
    if (client) {
      setEditDisplayName(client.display_name);
      setEditRateLimitRpm(client.rate_limit_rpm);
      setEditRateLimitTpm(client.rate_limit_tpm);
      setAllowUnrestricted(client.allowed_projects === null);
      setEditAllowedProjects(
        client.allowed_projects ? client.allowed_projects.join(", ") : ""
      );
    }
    setShowEditModal(true);
  }

  function handleUpdateClient() {
    const updates: ClientUpdateRequest = {};
    if (editDisplayName !== client?.display_name) {
      updates.display_name = editDisplayName;
    }
    if (editRateLimitRpm !== client?.rate_limit_rpm) {
      updates.rate_limit_rpm = editRateLimitRpm;
    }
    if (editRateLimitTpm !== client?.rate_limit_tpm) {
      updates.rate_limit_tpm = editRateLimitTpm;
    }
    // Handle allowed_projects
    if (!allowUnrestricted) {
      const projects = editAllowedProjects
        .split(",")
        .map((p) => p.trim())
        .filter(Boolean);
      updates.allowed_projects = projects;
    } else if (client?.allowed_projects !== null) {
      // Explicitly set to empty to mark as unrestricted (handled specially in backend)
      // Actually, we need a way to set null - let's use a special marker
      // For now, we won't allow changing from restricted to unrestricted via UI
      // (that requires direct DB access for security)
    }
    updateMutation.mutate(updates);
  }

  function handleCopySecret() {
    if (newSecret) {
      navigator.clipboard.writeText(newSecret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  const statusConfig = {
    active: { color: "text-emerald-400", bg: "bg-emerald-500/10", label: "Active" },
    suspended: { color: "text-amber-400", bg: "bg-amber-500/10", label: "Suspended" },
    blocked: { color: "text-red-400", bg: "bg-red-500/10", label: "Blocked" },
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-2 border-blue-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (error || !client) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 mb-4">Failed to load client</p>
          <button
            onClick={() => router.push("/access-control/clients")}
            className="text-blue-400 hover:text-blue-300"
          >
            Back to clients
          </button>
        </div>
      </div>
    );
  }

  const config = statusConfig[client.status as keyof typeof statusConfig] || statusConfig.active;

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push("/access-control/clients")}
              className="p-1 rounded hover:bg-slate-800 transition-colors"
            >
              <ArrowLeft className="h-5 w-5 text-slate-400" />
            </button>
            <Shield className="h-5 w-5 text-slate-400" />
            <h1 className="text-base font-semibold text-slate-100">{client.display_name}</h1>
            <span className={cn("text-xs px-2 py-1 rounded", config.bg, config.color)}>
              {config.label}
            </span>
          </div>
        </div>
      </header>

      <main className="relative max-w-3xl mx-auto px-6 py-8">
        {newSecret && (
          <div className="bg-amber-900/20 border border-amber-800/50 rounded-lg p-4 mb-6">
            <p className="text-sm text-amber-300 mb-2 font-medium">
              New secret generated - save it now!
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 p-3 bg-slate-950 rounded font-mono text-sm text-slate-100 break-all">
                {newSecret}
              </code>
              <button
                onClick={handleCopySecret}
                className="p-2 rounded bg-slate-800 hover:bg-slate-700 transition-colors"
              >
                {copied ? (
                  <Check className="h-5 w-5 text-emerald-400" />
                ) : (
                  <Copy className="h-5 w-5 text-slate-400" />
                )}
              </button>
            </div>
            <button
              onClick={() => setNewSecret(null)}
              className="mt-3 text-sm text-slate-400 hover:text-slate-300"
            >
              Dismiss
            </button>
          </div>
        )}

        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6 mb-6">
          <h2 className="text-sm font-semibold text-slate-300 mb-4">Client Details</h2>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-slate-400">Client ID</span>
              <p className="text-slate-100 font-mono mt-1">{client.client_id}</p>
            </div>
            <div>
              <span className="text-slate-400">Secret Prefix</span>
              <p className="text-slate-100 font-mono mt-1">{client.secret_prefix}...</p>
            </div>
            <div>
              <span className="text-slate-400">Type</span>
              <p className="text-slate-100 capitalize mt-1">{client.client_type}</p>
            </div>
            <div>
              <span className="text-slate-400">Status</span>
              <p className={cn("mt-1 capitalize", config.color)}>{client.status}</p>
            </div>
            <div>
              <span className="text-slate-400">Rate Limit (RPM)</span>
              <p className="text-slate-100 font-mono mt-1">{client.rate_limit_rpm}</p>
            </div>
            <div>
              <span className="text-slate-400">Rate Limit (TPM)</span>
              <p className="text-slate-100 font-mono mt-1">{client.rate_limit_tpm.toLocaleString()}</p>
            </div>
            <div className="col-span-2">
              <span className="text-slate-400">Allowed Projects</span>
              <p className="text-slate-100 mt-1">
                {client.allowed_projects === null ? (
                  <span className="text-emerald-400">Unrestricted (all projects)</span>
                ) : client.allowed_projects.length === 0 ? (
                  <span className="text-red-400">No projects allowed</span>
                ) : (
                  <span className="font-mono text-sm">
                    {client.allowed_projects.join(", ")}
                  </span>
                )}
              </p>
            </div>
            <div>
              <span className="text-slate-400">Created</span>
              <p className="text-slate-100 mt-1">{formatDate(client.created_at)}</p>
            </div>
            <div>
              <span className="text-slate-400">Last Used</span>
              <p className="text-slate-100 mt-1">{formatDate(client.last_used_at)}</p>
            </div>
          </div>

          {client.suspension_reason && (
            <div className="mt-4 pt-4 border-t border-slate-800">
              <span className="text-slate-400 text-sm">Suspension Reason</span>
              <p className="text-amber-300 mt-1">{client.suspension_reason}</p>
              {client.suspended_at && (
                <p className="text-slate-500 text-xs mt-1">
                  {client.status === "blocked" ? "Blocked" : "Suspended"} at {formatDate(client.suspended_at)}
                  {client.suspended_by && ` by ${client.suspended_by}`}
                </p>
              )}
            </div>
          )}
        </div>

        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-slate-300 mb-4">Actions</h2>
          <div className="flex flex-wrap gap-3">
            <button
              onClick={openEditModal}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 text-sm transition-colors"
            >
              <Pencil className="h-4 w-4" />
              Edit Settings
            </button>

            <button
              onClick={() => rotateSecretMutation.mutate()}
              disabled={rotateSecretMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 text-sm transition-colors disabled:opacity-50"
            >
              <RefreshCw className={cn("h-4 w-4", rotateSecretMutation.isPending && "animate-spin")} />
              Rotate Secret
            </button>

            {client.status === "active" && (
              <button
                onClick={() => setShowSuspendModal(true)}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 text-sm transition-colors"
              >
                <Ban className="h-4 w-4" />
                Suspend
              </button>
            )}

            {client.status === "suspended" && (
              <button
                onClick={() => activateMutation.mutate()}
                disabled={activateMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 text-sm transition-colors disabled:opacity-50"
              >
                <Play className="h-4 w-4" />
                Activate
              </button>
            )}

            {client.status !== "blocked" && (
              <button
                onClick={() => setShowBlockModal(true)}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600/20 hover:bg-red-600/30 text-red-300 text-sm transition-colors"
              >
                <Trash2 className="h-4 w-4" />
                Block Permanently
              </button>
            )}
          </div>
        </div>
      </main>

      {/* Suspend Modal */}
      {showSuspendModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-semibold text-slate-100 mb-4">Suspend Client</h3>
            <p className="text-sm text-slate-400 mb-4">
              The client will be temporarily blocked. You can reactivate it later.
            </p>
            <input
              type="text"
              value={suspendReason}
              onChange={(e) => setSuspendReason(e.target.value)}
              placeholder="Reason for suspension"
              className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-amber-500 mb-4"
            />
            <div className="flex gap-3">
              <button
                onClick={() => setShowSuspendModal(false)}
                className="flex-1 py-2 px-4 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 text-sm transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => suspendMutation.mutate(suspendReason)}
                disabled={!suspendReason.trim() || suspendMutation.isPending}
                className="flex-1 py-2 px-4 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-sm transition-colors disabled:opacity-50"
              >
                Suspend
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Block Modal */}
      {showBlockModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-semibold text-red-400 mb-4">Block Client Permanently</h3>
            <p className="text-sm text-slate-400 mb-4">
              This action cannot be undone. The client will be permanently blocked.
            </p>
            <input
              type="text"
              value={suspendReason}
              onChange={(e) => setSuspendReason(e.target.value)}
              placeholder="Reason for blocking"
              className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-red-500 mb-4"
            />
            <div className="flex gap-3">
              <button
                onClick={() => setShowBlockModal(false)}
                className="flex-1 py-2 px-4 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 text-sm transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => blockMutation.mutate(suspendReason)}
                disabled={!suspendReason.trim() || blockMutation.isPending}
                className="flex-1 py-2 px-4 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm transition-colors disabled:opacity-50"
              >
                Block Permanently
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {showEditModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg w-full mx-4">
            <h3 className="text-lg font-semibold text-slate-100 mb-4">Edit Client Settings</h3>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-slate-400 mb-1">Display Name</label>
                <input
                  type="text"
                  value={editDisplayName}
                  onChange={(e) => setEditDisplayName(e.target.value)}
                  className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-slate-400 mb-1">Rate Limit (RPM)</label>
                  <input
                    type="number"
                    value={editRateLimitRpm}
                    onChange={(e) => setEditRateLimitRpm(parseInt(e.target.value) || 60)}
                    min={1}
                    max={10000}
                    className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-slate-400 mb-1">Rate Limit (TPM)</label>
                  <input
                    type="number"
                    value={editRateLimitTpm}
                    onChange={(e) => setEditRateLimitTpm(parseInt(e.target.value) || 100000)}
                    min={1000}
                    max={10000000}
                    className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="flex items-center gap-2 text-sm text-slate-400 mb-2">
                  <input
                    type="checkbox"
                    checked={allowUnrestricted}
                    onChange={(e) => setAllowUnrestricted(e.target.checked)}
                    className="rounded bg-slate-800 border-slate-600 text-blue-500 focus:ring-blue-500"
                  />
                  Unrestricted (allow all projects)
                </label>
                {!allowUnrestricted && (
                  <div>
                    <label className="block text-sm text-slate-400 mb-1">
                      Allowed Projects (comma-separated)
                    </label>
                    <input
                      type="text"
                      value={editAllowedProjects}
                      onChange={(e) => setEditAllowedProjects(e.target.value)}
                      placeholder="project-1, project-2, project-3"
                      className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                    />
                    <p className="text-xs text-slate-500 mt-1">
                      Enter project IDs separated by commas. Leave empty to block all projects.
                    </p>
                  </div>
                )}
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setShowEditModal(false)}
                className="flex-1 py-2 px-4 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 text-sm transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleUpdateClient}
                disabled={updateMutation.isPending}
                className="flex-1 py-2 px-4 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm transition-colors disabled:opacity-50"
              >
                {updateMutation.isPending ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
