"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Key,
  Plus,
  Trash2,
  Edit2,
  Check,
  X,
  AlertCircle,
  Cpu,
  Server,
  Eye,
  EyeOff,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchCredentials,
  createCredential,
  updateCredential,
  deleteCredential,
  type Credential,
} from "@/lib/api";

const PROVIDERS = [
  { id: "claude", name: "Claude (Anthropic)", icon: Cpu, color: "orange" },
  { id: "gemini", name: "Gemini (Google)", icon: Server, color: "blue" },
] as const;

const CREDENTIAL_TYPES = [
  { id: "api_key", name: "API Key" },
  { id: "oauth_token", name: "OAuth Token" },
  { id: "refresh_token", name: "Refresh Token" },
] as const;

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");
  const [showValues, setShowValues] = useState<Record<number, boolean>>({});

  // Form state for new credential
  const [newCredential, setNewCredential] = useState({
    provider: "claude",
    credential_type: "api_key",
    value: "",
  });

  // Fetch credentials
  const { data, isLoading, error } = useQuery({
    queryKey: ["credentials"],
    queryFn: () => fetchCredentials(),
  });

  // Create mutation
  const createMutation = useMutation({
    mutationFn: createCredential,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      setShowAddForm(false);
      setNewCredential({
        provider: "claude",
        credential_type: "api_key",
        value: "",
      });
    },
  });

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, value }: { id: number; value: string }) =>
      updateCredential(id, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      setEditingId(null);
      setEditValue("");
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: deleteCredential,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
    },
  });

  const handleCreate = () => {
    if (!newCredential.value.trim()) return;
    createMutation.mutate(newCredential);
  };

  const handleUpdate = (id: number) => {
    if (!editValue.trim()) return;
    updateMutation.mutate({ id, value: editValue });
  };

  const handleDelete = (id: number) => {
    if (confirm("Are you sure you want to delete this credential?")) {
      deleteMutation.mutate(id);
    }
  };

  const startEdit = (credential: Credential) => {
    setEditingId(credential.id);
    setEditValue("");
  };

  const toggleShowValue = (id: number) => {
    setShowValues((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const getProviderConfig = (providerId: string) =>
    PROVIDERS.find((p) => p.id === providerId) || PROVIDERS[0];

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Page Header */}
      <header className="sticky top-0 z-10 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Settings
              </h1>
              <span className="text-sm text-slate-500 dark:text-slate-400">
                Credentials & preferences
              </span>
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-8 max-w-4xl">
        {/* Credentials Section */}
        <section className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Key className="h-5 w-5 text-slate-500" />
              <h2 className="text-lg font-medium text-slate-900 dark:text-slate-100">
                Provider Credentials
              </h2>
            </div>
            <button
              onClick={() => setShowAddForm(!showAddForm)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                showAddForm
                  ? "bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300"
                  : "bg-emerald-500 hover:bg-emerald-600 text-white",
              )}
            >
              {showAddForm ? (
                <>
                  <X className="h-4 w-4" />
                  Cancel
                </>
              ) : (
                <>
                  <Plus className="h-4 w-4" />
                  Add Credential
                </>
              )}
            </button>
          </div>

          {/* Add Form */}
          {showAddForm && (
            <div className="mb-6 p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
              <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-4">
                Add New Credential
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                    Provider
                  </label>
                  <select
                    value={newCredential.provider}
                    onChange={(e) =>
                      setNewCredential((prev) => ({
                        ...prev,
                        provider: e.target.value,
                      }))
                    }
                    className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm"
                  >
                    {PROVIDERS.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                    Type
                  </label>
                  <select
                    value={newCredential.credential_type}
                    onChange={(e) =>
                      setNewCredential((prev) => ({
                        ...prev,
                        credential_type: e.target.value,
                      }))
                    }
                    className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm"
                  >
                    {CREDENTIAL_TYPES.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                    Value
                  </label>
                  <input
                    type="password"
                    value={newCredential.value}
                    onChange={(e) =>
                      setNewCredential((prev) => ({
                        ...prev,
                        value: e.target.value,
                      }))
                    }
                    placeholder="sk-..."
                    className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm"
                  />
                </div>
              </div>
              <div className="mt-4 flex justify-end gap-2">
                <button
                  onClick={handleCreate}
                  disabled={
                    createMutation.isPending || !newCredential.value.trim()
                  }
                  className={cn(
                    "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                    "bg-emerald-500 hover:bg-emerald-600 text-white",
                    "disabled:opacity-50 disabled:cursor-not-allowed",
                  )}
                >
                  {createMutation.isPending ? (
                    "Saving..."
                  ) : (
                    <>
                      <Check className="h-4 w-4" />
                      Save Credential
                    </>
                  )}
                </button>
              </div>
              {createMutation.error && (
                <p className="mt-2 text-sm text-red-500">
                  {createMutation.error.message}
                </p>
              )}
            </div>
          )}

          {/* Error State */}
          {error && (
            <div className="flex items-center gap-2 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400">
              <AlertCircle className="h-5 w-5" />
              <p className="text-sm">Failed to load credentials</p>
            </div>
          )}

          {/* Loading State */}
          {isLoading && (
            <div className="flex items-center justify-center py-12 text-slate-500">
              Loading credentials...
            </div>
          )}

          {/* Credentials List */}
          {data && (
            <div className="space-y-3">
              {data.credentials.length === 0 ? (
                <div className="text-center py-12 text-slate-500 dark:text-slate-400">
                  <Key className="h-12 w-12 mx-auto mb-3 opacity-30" />
                  <p>No credentials configured</p>
                  <p className="text-sm mt-1">
                    Add your API keys to get started
                  </p>
                </div>
              ) : (
                data.credentials.map((credential) => {
                  const provider = getProviderConfig(credential.provider);
                  const isEditing = editingId === credential.id;
                  const isShowingValue = showValues[credential.id];

                  return (
                    <div
                      key={credential.id}
                      className={cn(
                        "flex items-center gap-4 p-4 rounded-lg border",
                        "bg-white dark:bg-slate-900",
                        provider.color === "orange"
                          ? "border-orange-200 dark:border-orange-900/50"
                          : "border-blue-200 dark:border-blue-900/50",
                      )}
                    >
                      {/* Provider Icon */}
                      <div
                        className={cn(
                          "p-2 rounded-lg",
                          provider.color === "orange"
                            ? "bg-orange-100 dark:bg-orange-900/30"
                            : "bg-blue-100 dark:bg-blue-900/30",
                        )}
                      >
                        <provider.icon
                          className={cn(
                            "h-5 w-5",
                            provider.color === "orange"
                              ? "text-orange-600 dark:text-orange-400"
                              : "text-blue-600 dark:text-blue-400",
                          )}
                        />
                      </div>

                      {/* Info */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-slate-900 dark:text-slate-100">
                            {provider.name}
                          </span>
                          <span className="px-2 py-0.5 rounded text-xs bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                            {credential.credential_type.replace("_", " ")}
                          </span>
                        </div>

                        {isEditing ? (
                          <div className="mt-2 flex items-center gap-2">
                            <input
                              type="password"
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              placeholder="Enter new value..."
                              className="flex-1 px-3 py-1.5 rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm"
                              autoFocus
                            />
                            <button
                              onClick={() => handleUpdate(credential.id)}
                              disabled={updateMutation.isPending}
                              className="p-1.5 rounded bg-emerald-500 text-white hover:bg-emerald-600 disabled:opacity-50"
                            >
                              <Check className="h-4 w-4" />
                            </button>
                            <button
                              onClick={() => {
                                setEditingId(null);
                                setEditValue("");
                              }}
                              className="p-1.5 rounded bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-300 dark:hover:bg-slate-600"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </div>
                        ) : (
                          <div className="mt-1 flex items-center gap-2">
                            <code className="text-sm font-mono text-slate-500 dark:text-slate-400">
                              {isShowingValue
                                ? credential.value_masked
                                : "••••••••••••"}
                            </code>
                            <button
                              onClick={() => toggleShowValue(credential.id)}
                              className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800"
                            >
                              {isShowingValue ? (
                                <EyeOff className="h-3.5 w-3.5 text-slate-400" />
                              ) : (
                                <Eye className="h-3.5 w-3.5 text-slate-400" />
                              )}
                            </button>
                          </div>
                        )}

                        <p className="mt-1 text-xs text-slate-400">
                          Updated{" "}
                          {new Date(credential.updated_at).toLocaleDateString()}
                        </p>
                      </div>

                      {/* Actions */}
                      {!isEditing && (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => startEdit(credential)}
                            className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                            title="Edit credential"
                          >
                            <Edit2 className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => handleDelete(credential.id)}
                            disabled={deleteMutation.isPending}
                            className="p-2 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 text-slate-500 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-50"
                            title="Delete credential"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          )}
        </section>

        {/* API Keys Section */}
        <section className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Key className="h-5 w-5 text-slate-500" />
              <h2 className="text-lg font-medium text-slate-900 dark:text-slate-100">
                API Keys
              </h2>
            </div>
            <a
              href="/settings/api-keys"
              className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
            >
              Manage API Keys →
            </a>
          </div>
          <div className="p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
            <p className="text-sm text-slate-600 dark:text-slate-400">
              Create and manage API keys for OpenAI-compatible access to Agent
              Hub.
            </p>
          </div>
        </section>

        {/* User Preferences Section */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Cpu className="h-5 w-5 text-slate-500" />
              <h2 className="text-lg font-medium text-slate-900 dark:text-slate-100">
                User Preferences
              </h2>
            </div>
            <a
              href="/settings/preferences"
              className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
            >
              Manage Preferences →
            </a>
          </div>
          <div className="p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
            <p className="text-sm text-slate-600 dark:text-slate-400">
              Configure response verbosity, tone, and default model preferences.
            </p>
          </div>
        </section>
      </main>
    </div>
  );
}
