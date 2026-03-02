"use client";

import { Shield } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Credential } from "@/lib/api";
import type { ProviderInfo } from "./constants";
import {
  type OAuthStatus,
  type OAuthProviderStatus,
  type ClaudeOAuthStatus,
  isClaudeStatus,
} from "./ProviderCardTypes";
import { VertexProjectInput } from "./VertexProjectInput";
import { timeAgo, formatDuration } from "./ProviderCardUtils";

interface ProviderStatusDisplayProps {
  provider: ProviderInfo;
  credentials: Credential[];
  oauthStatus?: OAuthStatus;
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
}

export function ProviderStatusDisplay({
  provider,
  credentials,
  oauthStatus,
  isConfigured,
  isOAuth,
  isClaude,
  hasOAuthToken,
  hasBothCredentials,
  preferredAuth,
  providerStatus,
  onPreferenceChange,
  vertexProject,
  onVertexProjectChange,
}: ProviderStatusDisplayProps) {
  if (isOAuth && isClaude && oauthStatus && isClaudeStatus(oauthStatus)) {
    return <ClaudeOAuthDisplay oauthStatus={oauthStatus} />;
  }

  // Primary credential for single-field providers
  const primaryCredential = credentials.find((c) => c.credential_type === "api_key") ?? credentials[0];

  if (isOAuth && !isClaude) {
    return (
      <NonClaudeOAuthDisplay
        provider={provider}
        credential={primaryCredential}
        isConfigured={isConfigured}
        hasOAuthToken={hasOAuthToken}
        hasBothCredentials={hasBothCredentials}
        preferredAuth={preferredAuth}
        providerStatus={providerStatus}
        onPreferenceChange={onPreferenceChange}
        vertexProject={vertexProject}
        onVertexProjectChange={onVertexProjectChange}
      />
    );
  }

  // Multi-field providers: show each credential
  if (isConfigured && provider.credentialFields && credentials.length > 0) {
    return (
      <div className="mt-0.5 space-y-0.5">
        {credentials.map((cred) => {
          const fieldDef = provider.credentialFields?.find(
            (f) => f.credentialType === cred.credential_type,
          );
          return (
            <p key={cred.id} className="text-xs text-slate-500 dark:text-slate-400 truncate">
              {fieldDef?.label ?? cred.credential_type}:{" "}
              <code className="font-mono">{cred.value_masked}</code>
              {" · Updated "}
              {timeAgo(cred.updated_at)}
            </p>
          );
        })}
      </div>
    );
  }

  // Single-field providers
  if (isConfigured && primaryCredential) {
    return (
      <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 truncate">
        <code className="font-mono">{primaryCredential.value_masked}</code>
        {" · Updated "}
        {timeAgo(primaryCredential.updated_at)}
      </p>
    );
  }

  return (
    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
      Not configured · {provider.hint}
    </p>
  );
}

function ClaudeOAuthDisplay({ oauthStatus }: { oauthStatus: ClaudeOAuthStatus }) {
  return (
    <div className="mt-0.5 space-y-0.5">
      <div className="flex items-center gap-1.5">
        <Shield className="h-3 w-3 text-amber-500" />
        <span className="text-xs text-amber-600 dark:text-amber-400 font-medium">
          OAuth
        </span>
        {oauthStatus.status === "valid" && (
          <span className="text-xs text-green-600 dark:text-green-400">· Active</span>
        )}
        {oauthStatus.status === "expired" && (
          <span className="text-xs text-red-500">
            · Expired — run `claude` to re-auth
          </span>
        )}
        {oauthStatus.status === "missing" && (
          <span className="text-xs text-slate-500">· Not authenticated</span>
        )}
      </div>
      {oauthStatus.status === "valid" && oauthStatus.expires_in_seconds != null && (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {oauthStatus.token_prefix && (
            <>
              <code className="font-mono text-[10px]">{oauthStatus.token_prefix}</code>
              {" · "}
            </>
          )}
          Expires in {formatDuration(oauthStatus.expires_in_seconds)}
          {oauthStatus.scopes && oauthStatus.scopes.length > 0 && (
            <> · {oauthStatus.scopes.join(", ")}</>
          )}
        </p>
      )}
    </div>
  );
}

interface NonClaudeOAuthDisplayProps {
  provider: ProviderInfo;
  credential?: Credential;
  isConfigured: boolean;
  hasOAuthToken: boolean;
  hasBothCredentials: boolean;
  preferredAuth: "oauth" | "api_key";
  providerStatus: OAuthProviderStatus | null;
  onPreferenceChange?: (pref: "oauth" | "api_key") => void;
  vertexProject?: string;
  onVertexProjectChange?: (project: string) => void;
}

function NonClaudeOAuthDisplay({
  provider,
  credential,
  isConfigured,
  hasOAuthToken,
  hasBothCredentials,
  preferredAuth,
  providerStatus,
  onPreferenceChange,
  vertexProject,
  onVertexProjectChange,
}: NonClaudeOAuthDisplayProps) {
  return (
    <div className="mt-0.5 space-y-0.5">
      <div className="flex items-center gap-1.5 flex-wrap">
        <Shield className="h-3 w-3 text-amber-500" />
        <span className="text-xs text-amber-600 dark:text-amber-400 font-medium">
          OAuth
        </span>
        {hasOAuthToken && (
          <span className="text-xs text-green-600 dark:text-green-400">
            · Active
            {providerStatus?.email && (
              <span className="text-slate-500"> ({providerStatus.email})</span>
            )}
          </span>
        )}
        {providerStatus?.oauth_status === "expired" && (
          <span className="text-xs text-red-500">· Expired</span>
        )}
        {providerStatus?.oauth_status === "not_configured" && (
          <span className="text-xs text-slate-500">· Not authenticated</span>
        )}
      </div>

      {provider.supportsApiKey && isConfigured && credential && (
        <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
          API key: <code className="font-mono">{credential.value_masked}</code>
          {" · Updated "}{timeAgo(credential.updated_at)}
        </p>
      )}

      {hasBothCredentials && provider.supportsApiKey && onPreferenceChange && (
        <div className="flex items-center gap-1 mt-1">
          <span className="text-[10px] text-slate-500 mr-1">Prefer:</span>
          <div className="flex rounded-md border border-slate-200 dark:border-slate-700 overflow-hidden">
            <button
              onClick={() => onPreferenceChange("oauth")}
              className={cn(
                "px-2 py-0.5 text-[10px] font-medium transition-colors",
                preferredAuth === "oauth"
                  ? "bg-blue-500 text-white"
                  : "bg-slate-50 dark:bg-slate-800 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700",
              )}
            >
              OAuth
            </button>
            <button
              onClick={() => onPreferenceChange("api_key")}
              className={cn(
                "px-2 py-0.5 text-[10px] font-medium transition-colors",
                preferredAuth === "api_key"
                  ? "bg-blue-500 text-white"
                  : "bg-slate-50 dark:bg-slate-800 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700",
              )}
            >
              API Key
            </button>
          </div>
        </div>
      )}

      {onVertexProjectChange && (
        <VertexProjectInput
          value={vertexProject ?? ""}
          onSave={onVertexProjectChange}
        />
      )}
    </div>
  );
}
