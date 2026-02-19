"use client";

import { Plus, Pencil, Trash2, Check, X, Loader2, Shield, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Credential } from "@/lib/api";
import { ProviderForm } from "./ProviderForm";
import type { ProviderInfo } from "./constants";

/** OAuth status from the /api/oauth/{provider}/status endpoint */
export interface OAuthProviderStatus {
  provider: string;
  oauth_status: "authenticated" | "expired" | "not_configured";
  api_key_status: "configured" | "not_configured";
  preferred_auth: "oauth" | "api_key";
  email?: string | null;
}

/** Claude-specific OAuth status (different shape) */
interface ClaudeOAuthStatus {
  status: "valid" | "expired" | "missing";
  token_prefix?: string | null;
  expires_in_seconds?: number | null;
  scopes?: string[];
}

/** Union type for all OAuth status shapes */
export type OAuthStatus = OAuthProviderStatus | ClaudeOAuthStatus;

function isClaudeStatus(s: OAuthStatus): s is ClaudeOAuthStatus {
  return "status" in s && !("oauth_status" in s);
}

interface ProviderCardProps {
  provider: ProviderInfo;
  credential?: Credential;
  oauthStatus?: OAuthStatus;
  colors: { dot: string; bg: string };
  isEditing: boolean;
  isAdding: boolean;
  isConfirmDelete: boolean;
  isSaving: boolean;
  error: string | null;
  onEdit: () => void;
  onAdd: () => void;
  onDelete: (id: number) => void;
  onSave: (value: string) => void;
  onCancel: () => void;
  onConfirmDelete: () => void;
  onCancelDelete: () => void;
  isDeletingThis: boolean;
  onOAuthStart?: () => void;
  isOAuthLoading?: boolean;
  onPreferenceChange?: (pref: "oauth" | "api_key") => void;
}

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatDuration(totalSeconds: number): string {
  const days = Math.floor(totalSeconds / 86400);
  if (days > 30) return `${Math.floor(days / 30)} months`;
  if (days > 0) return `${days}d`;
  const hours = Math.floor(totalSeconds / 3600);
  if (hours > 0) return `${hours}h`;
  const minutes = Math.floor(totalSeconds / 60);
  return `${minutes}m`;
}

/** Get normalized OAuth active state */
function getOAuthActive(status: OAuthStatus | undefined): "active" | "expired" | "missing" {
  if (!status) return "missing";
  if (isClaudeStatus(status)) {
    if (status.status === "valid") return "active";
    if (status.status === "expired") return "expired";
    return "missing";
  }
  if (status.oauth_status === "authenticated") return "active";
  if (status.oauth_status === "expired") return "expired";
  return "missing";
}

/** Check if any credential (OAuth or API key) is configured */
function hasAnyAuth(status: OAuthStatus | undefined, hasApiKey: boolean): boolean {
  if (hasApiKey) return true;
  if (!status) return false;
  if (isClaudeStatus(status)) return status.status === "valid";
  return status.oauth_status === "authenticated";
}

export function ProviderCard({
  provider,
  credential,
  oauthStatus,
  colors,
  isEditing,
  isAdding,
  isConfirmDelete,
  isSaving,
  error,
  onEdit,
  onAdd,
  onDelete,
  onSave,
  onCancel,
  onConfirmDelete,
  onCancelDelete,
  isDeletingThis,
  onOAuthStart,
  isOAuthLoading,
  onPreferenceChange,
}: ProviderCardProps) {
  const isConfigured = !!credential;
  const isOAuth = provider.oauth;
  const isFormOpen = isEditing || isAdding;
  const isClaude = provider.id === "claude";
  const oauthActive = getOAuthActive(oauthStatus);
  const anyAuth = hasAnyAuth(oauthStatus, isConfigured);

  // For providers with split status (codex, gemini)
  const providerStatus = oauthStatus && !isClaudeStatus(oauthStatus) ? oauthStatus : null;
  const hasOAuthToken = providerStatus?.oauth_status === "authenticated";
  const hasApiKey = providerStatus?.api_key_status === "configured" || isConfigured;
  const preferredAuth = providerStatus?.preferred_auth ?? "api_key";
  const hasBothCredentials = hasOAuthToken && hasApiKey;

  return (
    <div
      className={cn(
        "rounded-lg border p-4 transition-colors",
        anyAuth
          ? `border-slate-200 dark:border-slate-700 ${colors.bg}`
          : "border-slate-200 dark:border-slate-800 border-dashed"
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "h-2.5 w-2.5 rounded-full",
              isOAuth
                ? oauthActive === "active" || hasApiKey
                  ? "bg-green-400"
                  : oauthActive === "expired"
                    ? "bg-red-400"
                    : "bg-slate-300 dark:bg-slate-600"
                : isConfigured
                  ? colors.dot
                  : "bg-slate-300 dark:bg-slate-600"
            )}
          />
          <div>
            <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
              {provider.name}
            </p>
            {isOAuth && isClaude && isClaudeStatus(oauthStatus!) ? (
              /* Claude: CLI-managed OAuth display */
              <div className="mt-0.5 space-y-0.5">
                <div className="flex items-center gap-1.5">
                  <Shield className="h-3 w-3 text-amber-500" />
                  <span className="text-xs text-amber-600 dark:text-amber-400 font-medium">
                    OAuth
                  </span>
                  {oauthStatus && isClaudeStatus(oauthStatus) && (
                    <>
                      {oauthStatus.status === "valid" && (
                        <span className="text-xs text-green-600 dark:text-green-400">· Active</span>
                      )}
                      {oauthStatus.status === "expired" && (
                        <span className="text-xs text-red-500">· Expired — run `claude` to re-auth</span>
                      )}
                      {oauthStatus.status === "missing" && (
                        <span className="text-xs text-slate-500">· Not authenticated</span>
                      )}
                    </>
                  )}
                </div>
                {oauthStatus && isClaudeStatus(oauthStatus) && oauthStatus.status === "valid" &&
                  oauthStatus.expires_in_seconds != null && (
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {oauthStatus.token_prefix && (
                        <><code className="font-mono text-[10px]">{oauthStatus.token_prefix}</code>{" · "}</>
                      )}
                      Expires in {formatDuration(oauthStatus.expires_in_seconds)}
                      {oauthStatus.scopes && oauthStatus.scopes.length > 0 && (
                        <> · {oauthStatus.scopes.join(", ")}</>
                      )}
                    </p>
                  )}
              </div>
            ) : isOAuth && !isClaude ? (
              /* Non-Claude OAuth providers: show both OAuth and API key status */
              <div className="mt-0.5 space-y-0.5">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <Shield className="h-3 w-3 text-amber-500" />
                  <span className="text-xs text-amber-600 dark:text-amber-400 font-medium">OAuth</span>
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
                {/* Show API key status for dual-mode providers */}
                {provider.supportsApiKey && isConfigured && credential && (
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    API key: <code className="font-mono">{credential.value_masked}</code>
                    {" · Updated "}{timeAgo(credential.updated_at)}
                  </p>
                )}
                {/* Preference toggle when both exist */}
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
                            : "bg-slate-50 dark:bg-slate-800 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
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
                            : "bg-slate-50 dark:bg-slate-800 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
                        )}
                      >
                        API Key
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : isConfigured && credential ? (
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                <code className="font-mono">{credential.value_masked}</code>
                {" · Updated "}
                {timeAgo(credential.updated_at)}
              </p>
            ) : (
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Not configured · {provider.hint}
              </p>
            )}
          </div>
        </div>

        {/* Action buttons */}
        {!isFormOpen && (
          <div className="flex items-center gap-1">
            {/* OAuth providers (except Claude which is CLI-managed): always show authenticate */}
            {isOAuth && !isClaude && onOAuthStart && (
              <button
                onClick={onOAuthStart}
                disabled={isOAuthLoading}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50",
                  hasOAuthToken
                    ? "bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-400"
                    : "bg-blue-50 dark:bg-blue-950/30 hover:bg-blue-100 dark:hover:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                )}
              >
                {isOAuthLoading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <ExternalLink className="h-3.5 w-3.5" />
                )}
                {hasOAuthToken ? "Re-auth" : "Authenticate"}
              </button>
            )}

            {/* Add Key for dual-mode providers without a key */}
            {isOAuth && !isClaude && provider.supportsApiKey && !isConfigured && (
              <button
                onClick={onAdd}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
                Add Key
              </button>
            )}

            {/* API key management for dual-mode providers with a key, or non-OAuth providers */}
            {(!isOAuth || (provider.supportsApiKey && isConfigured)) && (
              <>
                {isConfigured && credential ? (
                  <>
                    {isConfirmDelete ? (
                      <div className="flex items-center gap-1">
                        <span className="text-xs text-red-500 mr-1">Delete?</span>
                        <button
                          onClick={() => onDelete(credential.id)}
                          disabled={isDeletingThis}
                          className="p-1.5 rounded-md bg-red-500 hover:bg-red-600 text-white transition-colors disabled:opacity-50"
                        >
                          {isDeletingThis ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Check className="h-3.5 w-3.5" />
                          )}
                        </button>
                        <button
                          onClick={onCancelDelete}
                          className="p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 transition-colors"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ) : (
                      <>
                        <button
                          onClick={onEdit}
                          className="p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors"
                          title="Edit key"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={onConfirmDelete}
                          className="p-1.5 rounded-md hover:bg-red-50 dark:hover:bg-red-950/30 text-slate-500 dark:text-slate-400 hover:text-red-500 transition-colors"
                          title="Delete key"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </>
                    )}
                  </>
                ) : !isOAuth ? (
                  <button
                    onClick={onAdd}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 transition-colors"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Add Key
                  </button>
                ) : null}
              </>
            )}
          </div>
        )}
      </div>

      {isFormOpen && (
        <ProviderForm
          providerName={provider.name}
          onSave={onSave}
          onCancel={onCancel}
          isSaving={isSaving}
          error={error}
        />
      )}
    </div>
  );
}
