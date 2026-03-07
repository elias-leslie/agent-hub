"use client";

import { cn } from "@/lib/utils";
import type { Credential } from "@/lib/api";
import type { ProviderInfo } from "./constants";
import {
  type OAuthStatus,
  type OAuthProviderStatus,
  type ProviderHealthData,
  isClaudeStatus,
} from "./ProviderCardTypes";
import { VertexProjectInput } from "./VertexProjectInput";
import { CredentialList } from "./CredentialList";
import {
  AuthBadges,
  HealthMetricsStrip,
  TimestampRow,
  PreferenceToggle,
} from "./ProviderStatusParts";

interface ProviderStatusDisplayProps {
  provider: ProviderInfo;
  credentials: Credential[];
  oauthStatus?: OAuthStatus;
  healthData?: ProviderHealthData;
  isConfigured: boolean;
  isOAuth: boolean;
  isClaude: boolean;
  hasOAuthToken: boolean;
  hasApiKey: boolean;
  hasBothCredentials: boolean;
  preferredAuth: "oauth" | "api_key";
  providerStatus: OAuthProviderStatus | null;
  onPreferenceChange?: (pref: "oauth" | "api_key") => void;
  vertexProject?: string;
  onVertexProjectChange?: (project: string) => void;
  onEditCredential?: (credentialId: number) => void;
  onDeleteCredential?: (credentialId: number) => void;
  onSetPrimaryCredential?: (credentialId: number) => void;
  pendingCredentialDeleteId?: number | null;
  onRequestDeleteCredential?: (credentialId: number) => void;
  onCancelDeleteCredential?: () => void;
}

export function ProviderStatusDisplay({
  provider,
  credentials,
  oauthStatus,
  healthData,
  isConfigured,
  isOAuth,
  isClaude,
  hasOAuthToken,
  hasApiKey,
  hasBothCredentials,
  preferredAuth,
  providerStatus,
  onPreferenceChange,
  vertexProject,
  onVertexProjectChange,
  onEditCredential,
  onDeleteCredential,
  onSetPrimaryCredential,
  pendingCredentialDeleteId,
  onRequestDeleteCredential,
  onCancelDeleteCredential,
}: ProviderStatusDisplayProps) {
  // Primary credential for single-field providers
  const primaryCredential = credentials.find((c) => c.credential_type === "api_key") ?? credentials[0];

  // Latest credential updated_at = "last authenticated"
  const authSince = credentials.length > 0
    ? credentials.reduce((latest, c) =>
      new Date(c.updated_at) > new Date(latest.updated_at) ? c : latest
    ).updated_at
    : null;

  // Not configured at all — show hint
  const noAuth = !isConfigured && (!isOAuth || !oauthStatus || (
    isClaudeStatus(oauthStatus) ? oauthStatus.status === "missing" : oauthStatus.oauth_status === "not_configured"
  ));

  if (noAuth && !healthData?.configured) {
    return (
      <p className="text-xs text-slate-500 mt-0.5">
        Not configured · {provider.hint}
      </p>
    );
  }

  return (
    <div className="mt-1 space-y-1.5">
      {/* Row 1: Auth method badges */}
      <AuthBadges
        isOAuth={isOAuth}
        isClaude={isClaude}
        oauthStatus={oauthStatus}
        hasOAuthToken={hasOAuthToken}
        hasApiKey={hasApiKey}
        isConfigured={isConfigured}
        primaryCredential={primaryCredential}
        providerStatus={providerStatus}
        hasBothCredentials={hasBothCredentials}
        preferredAuth={preferredAuth}
        onPreferenceChange={onPreferenceChange}
        provider={provider}
        credentials={credentials}
      />

      {/* Row 2: Health metrics strip (when health data available) */}
      {healthData?.health && healthData.configured && (
        <HealthMetricsStrip health={healthData.health} />
      )}

      {/* Row 3: Timestamps — authenticated since + last checked */}
      <TimestampRow
        authSince={authSince}
        healthData={healthData}
        isClaude={isClaude}
        oauthStatus={oauthStatus}
      />

      {/* Credential display (multi-field and single-field) */}
      <CredentialList
        credentials={credentials}
        provider={provider}
        isConfigured={isConfigured}
        onEditCredential={onEditCredential}
        onDeleteCredential={onDeleteCredential}
        onSetPrimaryCredential={onSetPrimaryCredential}
        pendingCredentialDeleteId={pendingCredentialDeleteId}
        onRequestDeleteCredential={onRequestDeleteCredential}
        onCancelDeleteCredential={onCancelDeleteCredential}
      />

      {/* Preference toggle for dual-auth providers */}
      {hasBothCredentials && provider.supportsApiKey && onPreferenceChange && (
        <PreferenceToggle preferredAuth={preferredAuth} onPreferenceChange={onPreferenceChange} />
      )}

      {/* Vertex project input */}
      {onVertexProjectChange && (
        <VertexProjectInput
          value={vertexProject ?? ""}
          onSave={onVertexProjectChange}
        />
      )}
    </div>
  );
}
