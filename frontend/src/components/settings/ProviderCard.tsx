'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { ManualPasteInput } from './ManualPasteInput'
import { ProviderActionButtons } from './ProviderActionButtons'
import {
  getOAuthActive,
  hasAnyAuth,
  type ProviderCardProps,
} from './ProviderCardTypes'
import { ProviderForm } from './ProviderForm'
import { ProviderStatusDisplay } from './ProviderStatusDisplay'

export type {
  OAuthProviderStatus,
  OAuthStatus,
} from './ProviderCardTypes'

export function ProviderCard({
  provider,
  credentials,
  oauthStatus,
  healthData,
  colors,
  isEditing,
  isAdding,
  isConfirmDelete,
  isSaving,
  error,
  onEdit,
  onAdd,
  onDeleteAll,
  onSave,
  onSaveMulti,
  onCancel,
  onConfirmDelete,
  onCancelDelete,
  isDeletingThis,
  onOAuthStart,
  onDisconnectOAuth,
  isOAuthLoading,
  isManualPasteActive,
  onManualExchange,
  onCancelManualPaste,
  preferredAuth: preferredAuthProp,
  onPreferenceChange,
  vertexProject,
  onVertexProjectChange,
  onEditCredential,
  onDeleteCredential,
  onSetPrimaryCredential,
}: ProviderCardProps) {
  const [isConfirmDisconnectOAuth, setIsConfirmDisconnectOAuth] =
    useState(false)
  const [pendingCredentialDeleteId, setPendingCredentialDeleteId] = useState<
    number | null
  >(null)
  const managedCredentials = provider.credentialFields
    ? credentials.filter((cred) =>
        provider.credentialFields?.some(
          (f) => f.credentialType === cred.credential_type,
        ),
      )
    : credentials.filter(
        (cred) => cred.credential_type === 'api_key' || !cred.credential_type,
      )

  const isConfigured = managedCredentials.length > 0
  const isOAuth = !!provider.oauth
  const isFormOpen = isEditing || isAdding
  const oauthActive = getOAuthActive(oauthStatus)
  const anyAuth = hasAnyAuth(oauthStatus, isConfigured)

  const providerStatus = oauthStatus ?? null
  const hasOAuthToken = oauthActive === 'active'
  const hasApiKey =
    providerStatus?.api_key_status === 'configured' || isConfigured
  const preferredAuth =
    preferredAuthProp ?? providerStatus?.preferred_auth ?? 'oauth'
  const hasBothCredentials = hasOAuthToken && hasApiKey

  // Health-aware styling
  const healthState = healthData?.health?.state
  const isHealthy = healthState === 'healthy'
  const isDegraded = healthState === 'degraded'
  const isDown = healthState === 'unavailable'

  // Dot color: health state takes priority when configured, else auth-based
  const dotColor = healthData?.configured
    ? isHealthy
      ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]'
      : isDegraded
        ? 'bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.4)]'
        : isDown
          ? 'bg-red-400 shadow-[0_0_6px_rgba(248,113,113,0.4)]'
          : 'bg-slate-400'
    : isOAuth
      ? oauthActive === 'active' || hasApiKey
        ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]'
        : oauthActive === 'expired'
          ? 'bg-red-400'
          : 'bg-slate-500'
      : isConfigured
        ? colors.dot
        : 'bg-slate-500'

  // Border color based on health when available
  const borderClass = healthData?.configured
    ? isHealthy
      ? 'border-emerald-500/20 bg-emerald-950/5'
      : isDegraded
        ? 'border-amber-500/20 bg-amber-950/5'
        : isDown
          ? 'border-red-500/25 bg-red-950/5'
          : 'border-slate-700'
    : anyAuth
      ? `border-slate-700 ${colors.bg}`
      : 'border-slate-800 border-dashed'

  return (
    <div className={cn('rounded-lg border p-3 transition-colors', borderClass)}>
      {/* Provider info row */}
      <div className="flex items-center gap-2.5 min-w-0">
        <div
          className={cn(
            'h-2.5 w-2.5 rounded-full shrink-0 transition-colors',
            dotColor,
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <p className="text-sm font-medium text-slate-100">
              {provider.name}
            </p>
          </div>
          <ProviderStatusDisplay
            provider={provider}
            credentials={managedCredentials}
            oauthStatus={oauthStatus}
            healthData={healthData}
            isConfigured={isConfigured}
            isOAuth={isOAuth}
            hasApiKey={hasApiKey}
            hasBothCredentials={hasBothCredentials}
            preferredAuth={preferredAuth}
            providerStatus={providerStatus}
            onPreferenceChange={onPreferenceChange}
            vertexProject={vertexProject}
            onVertexProjectChange={onVertexProjectChange}
            onEditCredential={onEditCredential}
            onDeleteCredential={(credentialId) => {
              onDeleteCredential?.(credentialId)
              setPendingCredentialDeleteId(null)
            }}
            onSetPrimaryCredential={onSetPrimaryCredential}
            pendingCredentialDeleteId={pendingCredentialDeleteId}
            onRequestDeleteCredential={(credentialId) => {
              setIsConfirmDisconnectOAuth(false)
              setPendingCredentialDeleteId(credentialId)
            }}
            onCancelDeleteCredential={() => setPendingCredentialDeleteId(null)}
          />
        </div>
      </div>

      {/* Action buttons — always below, left-aligned */}
      {!isFormOpen && (
        <div className="mt-2 ml-[1.25rem]">
          <ProviderActionButtons
            provider={provider}
            credentials={managedCredentials}
            isConfigured={isConfigured}
            isOAuth={isOAuth}
            isConfirmDelete={isConfirmDelete}
            isDeletingThis={isDeletingThis}
            hasOAuthToken={hasOAuthToken}
            onEdit={onEdit}
            onAdd={onAdd}
            onDeleteAll={onDeleteAll}
            onConfirmDelete={onConfirmDelete}
            onCancelDelete={onCancelDelete}
            onOAuthStart={onOAuthStart}
            onDisconnectOAuth={() => {
              onDisconnectOAuth?.()
              setIsConfirmDisconnectOAuth(false)
            }}
            isOAuthLoading={isOAuthLoading}
            isConfirmDisconnectOAuth={isConfirmDisconnectOAuth}
            onRequestDisconnectOAuth={() => {
              setPendingCredentialDeleteId(null)
              setIsConfirmDisconnectOAuth(true)
            }}
            onCancelDisconnectOAuth={() => setIsConfirmDisconnectOAuth(false)}
          />
        </div>
      )}

      {isManualPasteActive && onManualExchange && onCancelManualPaste && (
        <ManualPasteInput
          providerId={provider.id}
          onSubmit={onManualExchange}
          onCancel={onCancelManualPaste}
          error={error}
        />
      )}

      {isFormOpen && (
        <ProviderForm
          providerName={provider.name}
          onSave={onSave}
          saveOptions={isAdding ? { forceCreate: true } : undefined}
          onCancel={onCancel}
          isSaving={isSaving}
          error={error}
          credentialFields={provider.credentialFields}
          onSaveMulti={onSaveMulti}
        />
      )}
    </div>
  )
}
