"use client";

import { Loader2 } from "lucide-react";
import { PROVIDERS, PROVIDER_COLORS } from "./constants";
import { ProviderCard } from "./ProviderCard";
import { useProvidersTab, BROWSER_OAUTH_PROVIDERS } from "./useProvidersTab";

export function ProvidersTab() {
  const {
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
    isSaving,
    isDeletingAny,
    resetForm,
    handleSave,
    handleSaveMulti,
    handleOAuthStart,
    handleManualExchange,
    getOAuthStatus,
    onDelete,
    onPreferenceChange,
    onVertexProjectChange,
  } = useProvidersTab();

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
          const creds = credentialsByProvider[provider.id] ?? [];
          const colors = PROVIDER_COLORS[provider.id];
          const isEditing = editingProvider === provider.id;
          const isAdding = addingProvider === provider.id;
          const isConfirmDelete = confirmingDelete === provider.id;

          return (
            <ProviderCard
              key={provider.id}
              provider={provider}
              credentials={creds}
              oauthStatus={getOAuthStatus(provider.id)}
              colors={colors}
              isEditing={isEditing}
              isAdding={isAdding}
              isConfirmDelete={isConfirmDelete}
              isSaving={isSaving}
              error={error}
              onEdit={() => { resetForm(); setEditingProvider(provider.id); }}
              onAdd={() => { resetForm(); setAddingProvider(provider.id); }}
              onDeleteAll={(ids) => onDelete(ids)}
              onSave={(value) => handleSave(provider.id, value)}
              onSaveMulti={
                provider.credentialFields
                  ? (fields) => handleSaveMulti(provider.id, fields)
                  : undefined
              }
              onCancel={resetForm}
              onConfirmDelete={() => { setConfirmingDelete(provider.id); }}
              onCancelDelete={() => setConfirmingDelete(null)}
              isDeletingThis={isDeletingAny}
              onOAuthStart={
                BROWSER_OAUTH_PROVIDERS.includes(provider.id)
                  ? () => handleOAuthStart(provider.id)
                  : undefined
              }
              isOAuthLoading={oauthLoading === provider.id}
              isManualPasteActive={manualPasteProvider === provider.id}
              onManualExchange={(input) => handleManualExchange(provider.id, input)}
              onCancelManualPaste={() => {
                setManualPasteProvider(null);
                setManualPasteState(null);
                setOauthLoading(null);
              }}
              onPreferenceChange={
                provider.supportsApiKey
                  ? (pref) => onPreferenceChange(provider.id, pref)
                  : undefined
              }
              vertexProject={provider.id === "gemini" ? userPrefs?.gemini_vertex_project ?? "" : undefined}
              onVertexProjectChange={provider.id === "gemini" ? onVertexProjectChange : undefined}
            />
          );
        })}
      </div>
    </div>
  );
}
