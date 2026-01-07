"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  Key,
  Plus,
  Trash2,
  Copy,
  Check,
  X,
  AlertCircle,
  Clock,
  Activity,
  ArrowLeft,
  Ban,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchAPIKeys,
  createAPIKey,
  revokeAPIKey,
  deleteAPIKey,
  type APIKey,
  type APIKeyCreate,
  type APIKeyCreateResponse,
} from "@/lib/api";

function formatDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString();
}

function formatNumber(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  return value.toLocaleString();
}

export default function APIKeysPage() {
  const queryClient = useQueryClient();
  const [showAddForm, setShowAddForm] = useState(false);
  const [newKey, setNewKey] = useState<APIKeyCreateResponse | null>(null);
  const [copied, setCopied] = useState(false);

  // Form state for new key
  const [newKeyForm, setNewKeyForm] = useState<APIKeyCreate>({
    name: "",
    project_id: "default",
    rate_limit_rpm: 60,
    rate_limit_tpm: 100000,
    expires_in_days: undefined,
  });

  // Fetch keys
  const { data, isLoading, error } = useQuery({
    queryKey: ["api-keys"],
    queryFn: () => fetchAPIKeys({ include_revoked: true }),
  });

  // Create mutation
  const createMutation = useMutation({
    mutationFn: createAPIKey,
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
      setNewKey(response);
      setShowAddForm(false);
      setNewKeyForm({
        name: "",
        project_id: "default",
        rate_limit_rpm: 60,
        rate_limit_tpm: 100000,
        expires_in_days: undefined,
      });
    },
  });

  // Revoke mutation
  const revokeMutation = useMutation({
    mutationFn: revokeAPIKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: deleteAPIKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });

  const handleCreate = () => {
    createMutation.mutate({
      ...newKeyForm,
      name: newKeyForm.name || undefined,
      expires_in_days: newKeyForm.expires_in_days || undefined,
    });
  };

  const handleCopy = async () => {
    if (newKey) {
      await navigator.clipboard.writeText(newKey.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleRevoke = (id: number) => {
    if (confirm("Are you sure you want to revoke this API key? This cannot be undone.")) {
      revokeMutation.mutate(id);
    }
  };

  const handleDelete = (id: number) => {
    if (confirm("Permanently delete this API key? This cannot be undone.")) {
      deleteMutation.mutate(id);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Header */}
      <header className="sticky top-0 z-10 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-4">
              <Link
                href="/settings"
                className="p-2 -ml-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <ArrowLeft className="h-5 w-5 text-slate-500" />
              </Link>
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-amber-100 dark:bg-amber-900/30">
                  <Key className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                </div>
                <div>
                  <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                    API Keys
                  </h1>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    OpenAI-compatible authentication
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* New Key Created Banner */}
        {newKey && (
          <div className="mb-6 p-4 rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <h3 className="text-sm font-medium text-emerald-800 dark:text-emerald-200 mb-2">
                  API Key Created Successfully
                </h3>
                <p className="text-xs text-emerald-600 dark:text-emerald-400 mb-3">
                  Save this key now. You won&apos;t be able to see it again!
                </p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 px-3 py-2 rounded bg-white dark:bg-slate-800 font-mono text-sm text-slate-900 dark:text-slate-100 border border-emerald-200 dark:border-emerald-700">
                    {newKey.key}
                  </code>
                  <button
                    onClick={handleCopy}
                    className={cn(
                      "p-2 rounded-lg transition-colors",
                      copied
                        ? "bg-emerald-500 text-white"
                        : "bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700"
                    )}
                  >
                    {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  </button>
                </div>
              </div>
              <button
                onClick={() => setNewKey(null)}
                className="p-1 rounded hover:bg-emerald-200 dark:hover:bg-emerald-800"
              >
                <X className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
              </button>
            </div>
          </div>
        )}

        {/* Add Key Section */}
        <div className="flex items-center justify-between mb-6">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Create API keys for OpenAI-compatible access to Agent Hub.
          </p>
          <button
            onClick={() => setShowAddForm(!showAddForm)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
              showAddForm
                ? "bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300"
                : "bg-emerald-500 hover:bg-emerald-600 text-white"
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
                Create Key
              </>
            )}
          </button>
        </div>

        {/* Add Form */}
        {showAddForm && (
          <div className="mb-6 p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
            <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-4">
              Create New API Key
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                  Name (optional)
                </label>
                <input
                  type="text"
                  value={newKeyForm.name}
                  onChange={(e) => setNewKeyForm((prev) => ({ ...prev, name: e.target.value }))}
                  placeholder="My API Key"
                  className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                  Project ID
                </label>
                <input
                  type="text"
                  value={newKeyForm.project_id}
                  onChange={(e) => setNewKeyForm((prev) => ({ ...prev, project_id: e.target.value }))}
                  placeholder="default"
                  className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                  Rate Limit (requests/min)
                </label>
                <input
                  type="number"
                  value={newKeyForm.rate_limit_rpm}
                  onChange={(e) =>
                    setNewKeyForm((prev) => ({ ...prev, rate_limit_rpm: parseInt(e.target.value) || 60 }))
                  }
                  min={1}
                  max={1000}
                  className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                  Token Limit (tokens/min)
                </label>
                <input
                  type="number"
                  value={newKeyForm.rate_limit_tpm}
                  onChange={(e) =>
                    setNewKeyForm((prev) => ({
                      ...prev,
                      rate_limit_tpm: parseInt(e.target.value) || 100000,
                    }))
                  }
                  min={1000}
                  max={10000000}
                  className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                  Expires In (days, optional)
                </label>
                <input
                  type="number"
                  value={newKeyForm.expires_in_days || ""}
                  onChange={(e) =>
                    setNewKeyForm((prev) => ({
                      ...prev,
                      expires_in_days: e.target.value ? parseInt(e.target.value) : undefined,
                    }))
                  }
                  placeholder="Never expires"
                  min={1}
                  max={365}
                  className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm"
                />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={handleCreate}
                disabled={createMutation.isPending}
                className={cn(
                  "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium",
                  "bg-emerald-500 hover:bg-emerald-600 text-white",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                {createMutation.isPending ? (
                  "Creating..."
                ) : (
                  <>
                    <Check className="h-4 w-4" />
                    Create API Key
                  </>
                )}
              </button>
            </div>
            {createMutation.error && (
              <p className="mt-2 text-sm text-red-500">{createMutation.error.message}</p>
            )}
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="flex items-center gap-2 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400">
            <AlertCircle className="h-5 w-5" />
            <p className="text-sm">Failed to load API keys</p>
          </div>
        )}

        {/* Loading State */}
        {isLoading && (
          <div className="flex items-center justify-center py-12 text-slate-500">
            Loading API keys...
          </div>
        )}

        {/* Keys List */}
        {data && (
          <div className="space-y-3">
            {data.keys.length === 0 ? (
              <div className="text-center py-12 text-slate-500 dark:text-slate-400 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700">
                <Key className="h-12 w-12 mx-auto mb-3 opacity-30" />
                <p>No API keys</p>
                <p className="text-sm mt-1">Create your first API key to get started</p>
              </div>
            ) : (
              data.keys.map((apiKey) => (
                <APIKeyCard
                  key={apiKey.id}
                  apiKey={apiKey}
                  onRevoke={handleRevoke}
                  onDelete={handleDelete}
                  isRevoking={revokeMutation.isPending}
                  isDeleting={deleteMutation.isPending}
                />
              ))
            )}
          </div>
        )}

        {/* Usage Instructions */}
        <div className="mt-8 p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
          <div className="flex items-center gap-2 mb-3">
            <Settings className="h-4 w-4 text-slate-500" />
            <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300">
              Usage with OpenAI SDK
            </h3>
          </div>
          <pre className="text-xs font-mono text-slate-600 dark:text-slate-400 overflow-x-auto">
            {`from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8003/api/v1",
    api_key="sk-ah-..."  # Your API key
)

response = client.chat.completions.create(
    model="gpt-4",  # Maps to Claude Sonnet 4.5
    messages=[{"role": "user", "content": "Hello"}]
)`}
          </pre>
        </div>
      </main>
    </div>
  );
}

function APIKeyCard({
  apiKey,
  onRevoke,
  onDelete,
  isRevoking,
  isDeleting,
}: {
  apiKey: APIKey;
  onRevoke: (id: number) => void;
  onDelete: (id: number) => void;
  isRevoking: boolean;
  isDeleting: boolean;
}) {
  const isExpired = apiKey.expires_at && new Date(apiKey.expires_at) < new Date();

  return (
    <div
      className={cn(
        "flex items-center gap-4 p-4 rounded-lg border",
        "bg-white dark:bg-slate-900",
        !apiKey.is_active || isExpired
          ? "border-slate-300 dark:border-slate-700 opacity-60"
          : "border-amber-200 dark:border-amber-900/50"
      )}
    >
      {/* Icon */}
      <div
        className={cn(
          "p-2 rounded-lg",
          !apiKey.is_active || isExpired
            ? "bg-slate-100 dark:bg-slate-800"
            : "bg-amber-100 dark:bg-amber-900/30"
        )}
      >
        <Key
          className={cn(
            "h-5 w-5",
            !apiKey.is_active || isExpired
              ? "text-slate-400"
              : "text-amber-600 dark:text-amber-400"
          )}
        />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-slate-900 dark:text-slate-100">
            {apiKey.name || "Unnamed Key"}
          </span>
          <code className="px-2 py-0.5 rounded text-xs bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 font-mono">
            {apiKey.key_prefix}...
          </code>
          {!apiKey.is_active && (
            <span className="px-2 py-0.5 rounded text-xs bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400">
              Revoked
            </span>
          )}
          {isExpired && (
            <span className="px-2 py-0.5 rounded text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400">
              Expired
            </span>
          )}
        </div>

        <div className="mt-2 flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400 flex-wrap">
          <span className="flex items-center gap-1">
            <Activity className="h-3 w-3" />
            {formatNumber(apiKey.rate_limit_rpm)} rpm
          </span>
          <span>{formatNumber(apiKey.rate_limit_tpm)} tpm</span>
          <span>Project: {apiKey.project_id}</span>
          {apiKey.last_used_at && (
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Used {formatDate(apiKey.last_used_at)}
            </span>
          )}
        </div>

        <p className="mt-1 text-xs text-slate-400">
          Created {formatDate(apiKey.created_at)}
          {apiKey.expires_at && ` • Expires ${formatDate(apiKey.expires_at)}`}
        </p>
      </div>

      {/* Actions */}
      {apiKey.is_active && !isExpired && (
        <div className="flex items-center gap-1">
          <button
            onClick={() => onRevoke(apiKey.id)}
            disabled={isRevoking}
            className="p-2 rounded-lg hover:bg-amber-50 dark:hover:bg-amber-900/20 text-slate-500 hover:text-amber-600 dark:hover:text-amber-400 disabled:opacity-50"
            title="Revoke key"
          >
            <Ban className="h-4 w-4" />
          </button>
        </div>
      )}
      {!apiKey.is_active && (
        <button
          onClick={() => onDelete(apiKey.id)}
          disabled={isDeleting}
          className="p-2 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 text-slate-500 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-50"
          title="Delete permanently"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
