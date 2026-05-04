'use client'

import { Loader2 } from 'lucide-react'
import { getProviderInfo, isOAuthProvider, PROVIDER_COLORS } from './constants'
import { ProviderCard } from './ProviderCard'
import { useProvidersTab } from './useProvidersTab'

export function ProvidersTab() {
  const {
    isLoading,
    providerIds,
    credentialsByProvider,
    editingProvider,
    setEditingProvider,
    editingCredentialId,
    setEditingCredentialId,
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
    isSaving,
    isDeletingAny,
    resetForm,
    handleSave,
    handleSaveMulti,
    handleOAuthStart,
    handleManualExchange,
    getOAuthStatus,
    getHealthData,
    getPreferredAuth,
    handlePreferenceChange,
    onDelete,
    onSetPrimaryCredential,
  } = useProvidersTab()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-slate-500">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        Loading providers...
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-medium text-slate-100">
        Provider Credentials
      </h3>

      <div className="grid gap-3">
        {providerIds.map((providerId) => {
          const provider = getProviderInfo(providerId)
          const creds = credentialsByProvider[provider.id] ?? []
          const colors = PROVIDER_COLORS[provider.id] ?? {
            dot: 'bg-slate-400',
            bg: 'border-slate-500/20',
          }
          const isEditing = editingProvider === provider.id
          const isAdding = addingProvider === provider.id
          const isConfirmDelete = confirmingDelete === provider.id
          const primaryApiCredential = creds.find(
            (c) => c.credential_type === 'api_key' || !c.credential_type,
          )
          const oauthCredentialIds = creds
            .filter(
              (c) =>
                c.credential_type === 'oauth_token' ||
                c.credential_type === 'refresh_token',
            )
            .map((c) => c.id)

          return (
            <ProviderCard
              key={provider.id}
              provider={provider}
              credentials={creds}
              oauthStatus={getOAuthStatus(provider.id)}
              healthData={getHealthData(provider.id)}
              colors={colors}
              isEditing={isEditing}
              isAdding={isAdding}
              isConfirmDelete={isConfirmDelete}
              isSaving={isSaving}
              error={error}
              onEdit={() => {
                resetForm()
                setEditingCredentialId(primaryApiCredential?.id ?? null)
                setEditingProvider(provider.id)
              }}
              onAdd={() => {
                resetForm()
                setEditingCredentialId(null)
                setAddingProvider(provider.id)
              }}
              onDeleteAll={(ids) => onDelete(ids)}
              onSave={(value, options) =>
                handleSave(provider.id, value, {
                  ...options,
                  credentialId:
                    options?.credentialId ??
                    (isEditing
                      ? (editingCredentialId ?? undefined)
                      : undefined),
                  forceCreate: options?.forceCreate ?? isAdding,
                })
              }
              onSaveMulti={
                provider.credentialFields
                  ? (fields) => handleSaveMulti(provider.id, fields)
                  : undefined
              }
              onCancel={resetForm}
              onConfirmDelete={() => {
                setConfirmingDelete(provider.id)
              }}
              onCancelDelete={() => setConfirmingDelete(null)}
              isDeletingThis={isDeletingAny}
              onOAuthStart={
                isOAuthProvider(provider.id)
                  ? () => handleOAuthStart(provider.id)
                  : undefined
              }
              onDisconnectOAuth={
                oauthCredentialIds.length > 0
                  ? () => onDelete(oauthCredentialIds)
                  : undefined
              }
              isOAuthLoading={oauthLoading === provider.id}
              isManualPasteActive={manualPasteProvider === provider.id}
              onManualExchange={(input) =>
                handleManualExchange(provider.id, input)
              }
              onCancelManualPaste={() => {
                setManualPasteProvider(null)
                setManualPasteState(null)
                setOauthLoading(null)
              }}
              onEditCredential={(credentialId) => {
                resetForm()
                setEditingCredentialId(credentialId)
                setEditingProvider(provider.id)
              }}
              onDeleteCredential={(credentialId) => {
                onDelete([credentialId])
              }}
              preferredAuth={getPreferredAuth(provider.id)}
              onPreferenceChange={
                isOAuthProvider(provider.id)
                  ? (pref) => handlePreferenceChange(provider.id, pref)
                  : undefined
              }
              onSetPrimaryCredential={
                provider.id === 'gemini'
                  ? (credentialId) => onSetPrimaryCredential(credentialId)
                  : undefined
              }
            />
          )
        })}
      </div>
    </div>
  )
}
