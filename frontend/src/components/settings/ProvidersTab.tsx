"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchCredentials,
  fetchClaudeOAuthStatus,
  createCredential,
  updateCredential,
  deleteCredential,
  type Credential,
  type CredentialCreate,
} from "@/lib/api";
import { PROVIDERS, PROVIDER_COLORS } from "./constants";
import { ProviderCard } from "./ProviderCard";

export function ProvidersTab() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["credentials"],
    queryFn: () => fetchCredentials(),
  });
  const { data: oauthStatus } = useQuery({
    queryKey: ["claude-oauth-status"],
    queryFn: () => fetchClaudeOAuthStatus(),
  });

  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [addingProvider, setAddingProvider] = useState<string | null>(null);
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
              oauthStatus={provider.id === "claude" ? oauthStatus : undefined}
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
            />
          );
        })}
      </div>
    </div>
  );
}
