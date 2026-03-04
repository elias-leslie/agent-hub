"use client";

import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchCredentials,
  fetchClaudeOAuthStatus,
  fetchOAuthStatus,
  fetchStatus,
  startOAuthFlow,
  exchangeOAuthCode,
  createCredential,
  updateCredential,
  deleteCredential,
  updateUserPreferences,
  fetchUserPreferences,
  type Credential,
  type CredentialCreate,
} from "@/lib/api";
import type { ProviderHealthData } from "./ProviderCardTypes";

/** OAuth providers that support browser-based authentication */
export const BROWSER_OAUTH_PROVIDERS = ["claude", "codex", "gemini"];

export function useProvidersTab() {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["credentials"],
    queryFn: () => fetchCredentials(),
  });
  const { data: claudeOAuthStatus } = useQuery({
    queryKey: ["claude-oauth-status"],
    queryFn: () => fetchClaudeOAuthStatus(),
  });
  const { data: claudeOAuthProviderStatus } = useQuery({
    queryKey: ["oauth-status", "claude"],
    queryFn: () => fetchOAuthStatus("claude"),
  });
  const { data: codexOAuthStatus } = useQuery({
    queryKey: ["oauth-status", "codex"],
    queryFn: () => fetchOAuthStatus("codex"),
  });
  const { data: geminiOAuthStatus } = useQuery({
    queryKey: ["oauth-status", "gemini"],
    queryFn: () => fetchOAuthStatus("gemini"),
  });
  const { data: userPrefs } = useQuery({
    queryKey: ["user-preferences"],
    queryFn: () => fetchUserPreferences(),
  });
  const { data: statusData } = useQuery({
    queryKey: ["provider-status"],
    queryFn: () => fetchStatus(),
    refetchInterval: 30_000,
  });

  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [addingProvider, setAddingProvider] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [oauthLoading, setOauthLoading] = useState<string | null>(null);
  const [manualPasteProvider, setManualPasteProvider] = useState<string | null>(null);
  const [manualPasteState, setManualPasteState] = useState<string | null>(null);

  const credentialsByProvider: Record<string, Credential[]> = {};
  if (data) {
    for (const cred of data.credentials) {
      if (!credentialsByProvider[cred.provider]) {
        credentialsByProvider[cred.provider] = [];
      }
      credentialsByProvider[cred.provider].push(cred);
    }
  }

  const handleOAuthMessage = useCallback(
    (event: MessageEvent) => {
      if (event.data?.type === "oauth-success") {
        const provider = event.data.provider;
        setOauthLoading(null);
        setManualPasteProvider(null);
        setManualPasteState(null);
        queryClient.invalidateQueries({ queryKey: ["credentials"] });
        queryClient.invalidateQueries({ queryKey: ["claude-oauth-status"] });
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
      setManualPasteProvider(providerId);
      setManualPasteState(result.state);
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
        setError(`Popup blocked. Please open this URL manually: ${result.url}`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start OAuth flow");
      setOauthLoading(null);
      setManualPasteProvider(null);
      setManualPasteState(null);
    }
  }

  async function handleManualExchange(providerId: string, codeInput: string) {
    if (!manualPasteState) return;
    setError(null);
    try {
      const result = await exchangeOAuthCode(providerId, codeInput, manualPasteState);
      if (result.success) {
        setManualPasteProvider(null);
        setManualPasteState(null);
        setOauthLoading(null);
        queryClient.invalidateQueries({ queryKey: ["credentials"] });
        queryClient.invalidateQueries({ queryKey: ["claude-oauth-status"] });
        queryClient.invalidateQueries({ queryKey: ["oauth-status", providerId] });
      } else {
        setError(result.error || "OAuth exchange failed");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "OAuth exchange failed");
    }
  }

  const prefMut = useMutation({
    mutationFn: (args: { provider: string; pref: "oauth" | "api_key" }) => {
      const key = `${args.provider}_auth_preference` as "gemini_auth_preference" | "codex_auth_preference";
      return updateUserPreferences({ [key]: args.pref });
    },
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["oauth-status", vars.provider] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const vertexProjectMut = useMutation({
    mutationFn: (project: string) =>
      updateUserPreferences({ gemini_vertex_project: project }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user-preferences"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  function resetForm() {
    setEditingProvider(null);
    setAddingProvider(null);
    setError(null);
  }

  const createMut = useMutation({
    mutationFn: (d: CredentialCreate) => createCredential(d),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      if (BROWSER_OAUTH_PROVIDERS.includes(vars.provider)) {
        queryClient.invalidateQueries({ queryKey: ["oauth-status", vars.provider] });
      }
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
    mutationFn: (ids: number[]) => Promise.all(ids.map((id) => deleteCredential(id))),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      BROWSER_OAUTH_PROVIDERS.forEach((p) => {
        queryClient.invalidateQueries({ queryKey: ["oauth-status", p] });
      });
      setConfirmingDelete(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  function handleSave(providerId: string, value: string) {
    setError(null);
    const existing = credentialsByProvider[providerId]?.find(
      (c) => c.credential_type === "api_key",
    );
    if (existing) {
      updateMut.mutate({ id: existing.id, value });
    } else {
      createMut.mutate({ provider: providerId, credential_type: "api_key", value });
    }
  }

  async function handleSaveMulti(providerId: string, fields: Record<string, string>) {
    setError(null);
    const existing = credentialsByProvider[providerId] ?? [];
    try {
      for (const [credentialType, value] of Object.entries(fields)) {
        const match = existing.find((c) => c.credential_type === credentialType);
        if (match) {
          await updateCredential(match.id, value);
        } else {
          await createCredential({ provider: providerId, credential_type: credentialType, value });
        }
      }
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      resetForm();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save credentials");
    }
  }

  function getOAuthStatus(providerId: string) {
    if (providerId === "claude") return claudeOAuthStatus ?? claudeOAuthProviderStatus;
    if (providerId === "codex") return codexOAuthStatus;
    if (providerId === "gemini") return geminiOAuthStatus;
    return undefined;
  }

  function getHealthData(providerId: string): ProviderHealthData | undefined {
    if (!statusData) return undefined;
    // Status API uses adapter names which may differ from UI provider IDs
    const match = statusData.providers.find((p) => p.name === providerId);
    if (!match) return undefined;
    return {
      available: match.available,
      configured: match.configured,
      error: match.error,
      health: match.health,
    };
  }

  return {
    isLoading,
    credentialsByProvider,
    editingProvider,
    setEditingProvider,
    addingProvider,
    setAddingProvider,
    confirmingDelete,
    setConfirmingDelete,
    error,
    oauthLoading,
    manualPasteProvider,
    setManualPasteProvider,
    setManualPasteState,
    setOauthLoading,
    userPrefs,
    isSaving: createMut.isPending || updateMut.isPending,
    isDeletingAny: deleteMut.isPending,
    resetForm,
    handleSave,
    handleSaveMulti,
    handleOAuthStart,
    handleManualExchange,
    getOAuthStatus,
    getHealthData,
    onDelete: (ids: number[]) => deleteMut.mutate(ids),
    onPreferenceChange: (provider: string, pref: "oauth" | "api_key") =>
      prefMut.mutate({ provider, pref }),
    onVertexProjectChange: (project: string) => vertexProjectMut.mutate(project),
  };
}
