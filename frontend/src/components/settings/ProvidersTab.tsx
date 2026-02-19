"use client";

import { useState, useEffect, useCallback } from "react";
import { Loader2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchCredentials,
  fetchClaudeOAuthStatus,
  fetchOAuthStatus,
  startOAuthFlow,
  createCredential,
  updateCredential,
  deleteCredential,
  type Credential,
  type CredentialCreate,
} from "@/lib/api";
import { PROVIDERS, PROVIDER_COLORS } from "./constants";
import { ProviderCard } from "./ProviderCard";

/** OAuth providers that support browser-based authentication (not Claude, which is CLI-only) */
const BROWSER_OAUTH_PROVIDERS = ["codex", "gemini"];

export function ProvidersTab() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["credentials"],
    queryFn: () => fetchCredentials(),
  });
  const { data: claudeOAuthStatus } = useQuery({
    queryKey: ["claude-oauth-status"],
    queryFn: () => fetchClaudeOAuthStatus(),
  });

  // OAuth status for browser-based providers
  const { data: codexOAuthStatus } = useQuery({
    queryKey: ["oauth-status", "codex"],
    queryFn: () => fetchOAuthStatus("codex"),
  });
  const { data: geminiOAuthStatus } = useQuery({
    queryKey: ["oauth-status", "gemini"],
    queryFn: () => fetchOAuthStatus("gemini"),
  });

  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [addingProvider, setAddingProvider] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [oauthLoading, setOauthLoading] = useState<string | null>(null);

  const credentialsByProvider: Record<string, Credential> = {};
  if (data) {
    for (const cred of data.credentials) {
      credentialsByProvider[cred.provider] = cred;
    }
  }

  // Listen for OAuth success/error messages from popup windows
  const handleOAuthMessage = useCallback(
    (event: MessageEvent) => {
      if (event.data?.type === "oauth-success") {
        const provider = event.data.provider;
        setOauthLoading(null);
        // Refresh both credentials list and OAuth status
        queryClient.invalidateQueries({ queryKey: ["credentials"] });
        if (BROWSER_OAUTH_PROVIDERS.includes(provider)) {
          queryClient.invalidateQueries({ queryKey: ["oauth-status", provider] });
        }
      } else if (event.data?.type === "oauth-error") {
        setOauthLoading(null);
        setError(event.data.error || "OAuth authentication failed");
      }
    },
    [queryClient],
  );

  useEffect(() => {
    window.addEventListener("message", handleOAuthMessage);
    return () => window.removeEventListener("message", handleOAuthMessage);
  }, [handleOAuthMessage]);

  async function handleOAuthStart(providerId: string) {
    setError(null);
    setOauthLoading(providerId);
    try {
      const result = await startOAuthFlow(providerId);
      // Open auth URL in popup
      const width = 600;
      const height = 700;
      const left = window.screenX + (window.outerWidth - width) / 2;
      const top = window.screenY + (window.outerHeight - height) / 2;
      const popup = window.open(
        result.url,
        `oauth-${providerId}`,
        `width=${width},height=${height},left=${left},top=${top},popup=yes`,
      );

      if (!popup) {
        // Popup blocked — show URL as fallback
        setError(
          `Popup blocked. Please open this URL manually: ${result.url}`,
        );
        setOauthLoading(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start OAuth flow");
      setOauthLoading(null);
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
    setError(null);
  }

  function handleSave(providerId: string, value: string) {
    setError(null);
    const existing = credentialsByProvider[providerId];
    if (existing) {
      updateMut.mutate({ id: existing.id, value });
    } else {
      createMut.mutate({
        provider: providerId,
        credential_type: "api_key",
        value,
      });
    }
  }

  function getOAuthStatus(providerId: string) {
    if (providerId === "claude") {
      return claudeOAuthStatus;
    }
    if (providerId === "codex" && codexOAuthStatus) {
      // Normalize to the shape ProviderCard expects
      return {
        status: codexOAuthStatus.status === "authenticated" ? "valid" as const
          : codexOAuthStatus.status === "not_configured" ? "missing" as const
          : "expired" as const,
        email: codexOAuthStatus.email,
      };
    }
    if (providerId === "gemini" && geminiOAuthStatus) {
      return {
        status: geminiOAuthStatus.status === "authenticated" ? "valid" as const
          : geminiOAuthStatus.status === "not_configured" ? "missing" as const
          : "expired" as const,
        email: geminiOAuthStatus.email,
      };
    }
    return undefined;
  }

  const isSaving = createMut.isPending || updateMut.isPending;

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
          const isEditing = editingProvider === provider.id;
          const isAdding = addingProvider === provider.id;
          const isConfirmDelete = confirmingDelete === provider.id;

          return (
            <ProviderCard
              key={provider.id}
              provider={provider}
              credential={cred}
              oauthStatus={getOAuthStatus(provider.id)}
              colors={colors}
              isEditing={isEditing}
              isAdding={isAdding}
              isConfirmDelete={isConfirmDelete}
              isSaving={isSaving}
              error={error}
              onEdit={() => {
                resetForm();
                setEditingProvider(provider.id);
              }}
              onAdd={() => {
                resetForm();
                setAddingProvider(provider.id);
              }}
              onDelete={(id) => deleteMut.mutate(id)}
              onSave={(value) => handleSave(provider.id, value)}
              onCancel={resetForm}
              onConfirmDelete={() => {
                setError(null);
                setConfirmingDelete(provider.id);
              }}
              onCancelDelete={() => setConfirmingDelete(null)}
              isDeletingThis={deleteMut.isPending}
              onOAuthStart={
                BROWSER_OAUTH_PROVIDERS.includes(provider.id)
                  ? () => handleOAuthStart(provider.id)
                  : undefined
              }
              isOAuthLoading={oauthLoading === provider.id}
            />
          );
        })}
      </div>
    </div>
  );
}
