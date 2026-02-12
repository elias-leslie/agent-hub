"use client";

import { useState, useEffect } from "react";
import {
  X,
  Key,
  Sliders,
  Plus,
  Pencil,
  Trash2,
  Check,
  Loader2,
  Shield,
  Eye,
  EyeOff,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchCredentials,
  createCredential,
  updateCredential,
  deleteCredential,
  type Credential,
  type CredentialCreate,
} from "@/lib/api";

const TABS = [
  { id: "preferences", label: "Preferences", icon: Sliders },
  { id: "providers", label: "LLM Providers", icon: Key },
] as const;

type TabId = (typeof TABS)[number]["id"];

const PROVIDERS = [
  { id: "claude", name: "Claude", hint: "OAuth via CLI — no key needed", oauth: true },
  { id: "gemini", name: "Gemini", hint: "Google AI API key" },
  { id: "openai", name: "OpenAI", hint: "OpenAI platform API key" },
  { id: "openrouter", name: "OpenRouter", hint: "OpenRouter API key" },
  { id: "xai", name: "xAI", hint: "xAI (Grok) API key" },
  { id: "zhipu", name: "Zhipu", hint: "Zhipu AI (GLM) API key" },
] as const;

const PROVIDER_COLORS: Record<string, { dot: string; bg: string }> = {
  claude:     { dot: "bg-amber-400",  bg: "border-amber-500/20" },
  gemini:     { dot: "bg-blue-400",   bg: "border-blue-500/20" },
  openai:     { dot: "bg-green-400",  bg: "border-green-500/20" },
  openrouter: { dot: "bg-purple-400", bg: "border-purple-500/20" },
  xai:        { dot: "bg-red-400",    bg: "border-red-500/20" },
  zhipu:      { dot: "bg-teal-400",   bg: "border-teal-500/20" },
};

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<TabId>("preferences");

  useEffect(() => {
    if (!isOpen) setActiveTab("preferences");
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative w-full max-w-3xl mx-4 rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Settings
          </h2>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 px-6 pt-4 border-b border-slate-200 dark:border-slate-800">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors",
                  isActive
                    ? "border-amber-500 text-amber-600 dark:text-amber-400"
                    : "border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300"
                )}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Content */}
        <div className="p-6 max-h-[60vh] overflow-y-auto">
          {activeTab === "preferences" && <PreferencesTab />}
          {activeTab === "providers" && <ProvidersTab />}
        </div>
      </div>
    </div>
  );
}

function PreferencesTab() {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-medium text-slate-900 dark:text-slate-100 mb-3">
          Response Preferences
        </h3>
        <div className="space-y-3">
          <div className="flex items-center justify-between p-3 rounded-lg border border-slate-200 dark:border-slate-700">
            <div>
              <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                Response Verbosity
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Control detail level in responses
              </p>
            </div>
            <select className="px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm">
              <option>Concise</option>
              <option>Balanced</option>
              <option>Detailed</option>
            </select>
          </div>
          <div className="flex items-center justify-between p-3 rounded-lg border border-slate-200 dark:border-slate-700">
            <div>
              <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                Default Model
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Preferred model for new sessions
              </p>
            </div>
            <select className="px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm">
              <option>claude-sonnet-4-5</option>
              <option>claude-haiku-4-5</option>
              <option>gemini-2.0-flash</option>
            </select>
          </div>
        </div>
      </div>
      <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Preferences are saved locally and applied to future sessions.
        </p>
      </div>
    </div>
  );
}

function ProvidersTab() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["credentials"],
    queryFn: () => fetchCredentials(),
  });

  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [addingProvider, setAddingProvider] = useState<string | null>(null);
  const [keyValue, setKeyValue] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const credentialsByProvider: Record<string, Credential> = {};
  if (data) {
    for (const cred of data.credentials) {
      credentialsByProvider[cred.provider] = cred;
    }
  }

  const createMut = useMutation({
    mutationFn: (d: CredentialCreate) => createCredential(d),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      resetForm();
    },
    onError: (e: Error) => setError(e.message),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, value }: { id: number; value: string }) =>
      updateCredential(id, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      resetForm();
    },
    onError: (e: Error) => setError(e.message),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteCredential(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      setConfirmingDelete(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  function resetForm() {
    setEditingProvider(null);
    setAddingProvider(null);
    setKeyValue("");
    setShowPassword(false);
    setError(null);
  }

  function handleSave(providerId: string) {
    if (!keyValue.trim()) return;
    setError(null);
    const existing = credentialsByProvider[providerId];
    if (existing) {
      updateMut.mutate({ id: existing.id, value: keyValue.trim() });
    } else {
      createMut.mutate({
        provider: providerId,
        credential_type: "api_key",
        value: keyValue.trim(),
      });
    }
  }

  const isSaving = createMut.isPending || updateMut.isPending;

  function timeAgo(dateStr: string): string {
    const seconds = Math.floor(
      (Date.now() - new Date(dateStr).getTime()) / 1000,
    );
    if (seconds < 60) return "just now";
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-slate-500">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        Loading providers...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-medium text-slate-900 dark:text-slate-100">
        Provider Credentials
      </h3>

      <div className="grid gap-3">
        {PROVIDERS.map((provider) => {
          const cred = credentialsByProvider[provider.id];
          const colors = PROVIDER_COLORS[provider.id];
          const isConfigured = !!cred;
          const isOAuth = "oauth" in provider && provider.oauth;
          const isEditing = editingProvider === provider.id;
          const isAdding = addingProvider === provider.id;
          const isConfirmDelete = confirmingDelete === provider.id;
          const isFormOpen = isEditing || isAdding;

          return (
            <div
              key={provider.id}
              className={cn(
                "rounded-lg border p-4 transition-colors",
                isConfigured || isOAuth
                  ? `border-slate-200 dark:border-slate-700 ${colors?.bg}`
                  : "border-slate-200 dark:border-slate-800 border-dashed",
              )}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className={cn(
                      "h-2.5 w-2.5 rounded-full",
                      isConfigured || isOAuth
                        ? colors?.dot
                        : "bg-slate-300 dark:bg-slate-600",
                    )}
                  />
                  <div>
                    <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                      {provider.name}
                    </p>
                    {isOAuth ? (
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <Shield className="h-3 w-3 text-amber-500" />
                        <span className="text-xs text-amber-600 dark:text-amber-400 font-medium">
                          OAuth
                        </span>
                        <span className="text-xs text-slate-500 dark:text-slate-400">
                          — {provider.hint}
                        </span>
                      </div>
                    ) : isConfigured ? (
                      <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                        <code className="font-mono">
                          {cred.value_masked}
                        </code>
                        {" · Updated "}
                        {timeAgo(cred.updated_at)}
                      </p>
                    ) : (
                      <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                        Not configured · {provider.hint}
                      </p>
                    )}
                  </div>
                </div>

                {!isOAuth && !isFormOpen && (
                  <div className="flex items-center gap-1">
                    {isConfigured ? (
                      <>
                        {isConfirmDelete ? (
                          <div className="flex items-center gap-1">
                            <span className="text-xs text-red-500 mr-1">
                              Delete?
                            </span>
                            <button
                              onClick={() => deleteMut.mutate(cred.id)}
                              disabled={deleteMut.isPending}
                              className="p-1.5 rounded-md bg-red-500 hover:bg-red-600 text-white transition-colors disabled:opacity-50"
                            >
                              {deleteMut.isPending ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Check className="h-3.5 w-3.5" />
                              )}
                            </button>
                            <button
                              onClick={() => setConfirmingDelete(null)}
                              className="p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 transition-colors"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ) : (
                          <>
                            <button
                              onClick={() => {
                                resetForm();
                                setEditingProvider(provider.id);
                              }}
                              className="p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors"
                              title="Edit key"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => {
                                setError(null);
                                setConfirmingDelete(provider.id);
                              }}
                              className="p-1.5 rounded-md hover:bg-red-50 dark:hover:bg-red-950/30 text-slate-500 dark:text-slate-400 hover:text-red-500 transition-colors"
                              title="Delete key"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </>
                        )}
                      </>
                    ) : (
                      <button
                        onClick={() => {
                          resetForm();
                          setAddingProvider(provider.id);
                        }}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 transition-colors"
                      >
                        <Plus className="h-3.5 w-3.5" />
                        Add Key
                      </button>
                    )}
                  </div>
                )}
              </div>

              {isFormOpen && (
                <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700">
                  <div className="flex items-center gap-2">
                    <div className="relative flex-1">
                      <input
                        type={showPassword ? "text" : "password"}
                        value={keyValue}
                        onChange={(e) => setKeyValue(e.target.value)}
                        placeholder={`Enter ${provider.name} API key`}
                        className="w-full px-3 py-2 pr-9 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500"
                        autoFocus
                        onKeyDown={(e) => {
                          if (e.key === "Enter") handleSave(provider.id);
                          if (e.key === "Escape") resetForm();
                        }}
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                      >
                        {showPassword ? (
                          <EyeOff className="h-3.5 w-3.5" />
                        ) : (
                          <Eye className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </div>
                    <button
                      onClick={() => handleSave(provider.id)}
                      disabled={!keyValue.trim() || isSaving}
                      className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-amber-500 hover:bg-amber-600 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isSaving ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Check className="h-3.5 w-3.5" />
                      )}
                      Save
                    </button>
                    <button
                      onClick={resetForm}
                      className="px-3 py-2 rounded-lg text-xs font-medium hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                  {error && (
                    <p className="mt-2 text-xs text-red-500">{error}</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
