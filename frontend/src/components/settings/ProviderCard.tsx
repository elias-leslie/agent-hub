"use client";

import { cn } from "@/lib/utils";
import { ProviderForm } from "./ProviderForm";
import {
  type ProviderCardProps,
  getOAuthActive,
  hasAnyAuth,
  isClaudeStatus,
} from "./ProviderCardTypes";
import { PROVIDER_ID_CLAUDE } from "./ProviderCardUtils";
import { ProviderStatusDisplay } from "./ProviderStatusDisplay";
import { ProviderActionButtons } from "./ProviderActionButtons";
import { ManualPasteInput } from "./ManualPasteInput";

export type { OAuthProviderStatus, ClaudeOAuthStatus, OAuthStatus } from "./ProviderCardTypes";

export function ProviderCard({
  provider,
  credentials,
  oauthStatus,
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
  isOAuthLoading,
  isManualPasteActive,
  onManualExchange,
  onCancelManualPaste,
  onPreferenceChange,
  vertexProject,
  onVertexProjectChange,
}: ProviderCardProps) {
  // Primary credential (api_key) for backward-compat display
  const primaryCredential = credentials.find((c) => c.credential_type === "api_key") ?? credentials[0];
  const isConfigured = credentials.length > 0;
  const isOAuth = !!provider.oauth;
  const isFormOpen = isEditing || isAdding;
  const isClaude = provider.id === PROVIDER_ID_CLAUDE;
  const oauthActive = getOAuthActive(oauthStatus);
  const anyAuth = hasAnyAuth(oauthStatus, isConfigured);

  const providerStatus =
    oauthStatus && !isClaudeStatus(oauthStatus) ? oauthStatus : null;
  const hasOAuthToken = providerStatus?.oauth_status === "authenticated";
  const hasApiKey = providerStatus?.api_key_status === "configured" || isConfigured;
  const preferredAuth = providerStatus?.preferred_auth ?? "api_key";
  const hasBothCredentials = hasOAuthToken && hasApiKey;

  const dotColor = isOAuth
    ? oauthActive === "active" || hasApiKey
      ? "bg-green-400"
      : oauthActive === "expired"
        ? "bg-red-400"
        : "bg-slate-300 dark:bg-slate-600"
    : isConfigured
      ? colors.dot
      : "bg-slate-300 dark:bg-slate-600";

  return (
    <div
      className={cn(
        "rounded-lg border p-4 transition-colors",
        anyAuth
          ? `border-slate-200 dark:border-slate-700 ${colors.bg}`
          : "border-slate-200 dark:border-slate-800 border-dashed",
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={cn("h-2.5 w-2.5 rounded-full", dotColor)} />
          <div>
            <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
              {provider.name}
            </p>
            <ProviderStatusDisplay
              provider={provider}
              credentials={credentials}
              oauthStatus={oauthStatus}
              isConfigured={isConfigured}
              isOAuth={isOAuth}
              isClaude={isClaude}
              hasOAuthToken={hasOAuthToken}
              hasApiKey={hasApiKey}
              hasBothCredentials={hasBothCredentials}
              preferredAuth={preferredAuth}
              providerStatus={providerStatus}
              onPreferenceChange={onPreferenceChange}
              vertexProject={vertexProject}
              onVertexProjectChange={onVertexProjectChange}
            />
          </div>
        </div>

        {!isFormOpen && (
          <ProviderActionButtons
            provider={provider}
            credentials={credentials}
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
            isOAuthLoading={isOAuthLoading}
          />
        )}
      </div>

      {isManualPasteActive && onManualExchange && onCancelManualPaste && (
        <ManualPasteInput
          providerId={provider.id}
          onSubmit={onManualExchange}
          onCancel={onCancelManualPaste}
        />
      )}

      {isFormOpen && (
        <ProviderForm
          providerName={provider.name}
          onSave={onSave}
          onCancel={onCancel}
          isSaving={isSaving}
          error={error}
          credentialFields={provider.credentialFields}
          onSaveMulti={onSaveMulti}
        />
      )}
    </div>
  );
}
