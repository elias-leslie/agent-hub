"use client";

import { Plus, Pencil, Trash2, Check, X, Loader2, Shield, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Credential } from "@/lib/api";
import { ProviderForm } from "./ProviderForm";
import type { ProviderInfo } from "./constants";

interface OAuthStatus {
  status: "valid" | "expired" | "missing" | "authenticated" | "not_configured";
  token_prefix?: string | null;
  expires_in_seconds?: number | null;
  scopes?: string[];
  email?: string | null;
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

/** Normalize various status strings to a unified set */
function normalizeOAuthStatus(status: string | undefined): "active" | "expired" | "missing" {
  if (status === "valid" || status === "authenticated") return "active";
  if (status === "expired") return "expired";
  return "missing";
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
}: ProviderCardProps) {
  const isConfigured = !!credential;
  const isOAuth = provider.oauth;
  const isFormOpen = isEditing || isAdding;
  const isClaude = provider.id === "claude";
  const normalized = normalizeOAuthStatus(oauthStatus?.status);

  return (
    <div
      className={cn(
        "rounded-lg border p-4 transition-colors",
        isConfigured || (isOAuth && normalized === "active")
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
                ? normalized === "active"
                  ? "bg-green-400"
                  : normalized === "expired"
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
            {isOAuth ? (
              <div className="mt-0.5 space-y-0.5">
                <div className="flex items-center gap-1.5">
                  <Shield className="h-3 w-3 text-amber-500" />
                  <span className="text-xs text-amber-600 dark:text-amber-400 font-medium">
                    OAuth
                  </span>
                  {normalized === "active" && (
                    <span className="text-xs text-green-600 dark:text-green-400">
                      · Active
                      {oauthStatus?.email && (
                        <span className="text-slate-500"> ({oauthStatus.email})</span>
                      )}
                    </span>
                  )}
                  {normalized === "expired" && (
                    <span className="text-xs text-red-500">
                      · Expired
                      {isClaude && " — run `claude` to re-auth"}
                    </span>
                  )}
                  {normalized === "missing" && (
                    <span className="text-xs text-slate-500">
                      · Not authenticated
                    </span>
                  )}
                </div>
                {normalized === "active" &&
                  oauthStatus?.expires_in_seconds != null && (
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {oauthStatus.token_prefix && (
                        <>
                          <code className="font-mono text-[10px]">
                            {oauthStatus.token_prefix}
                          </code>
                          {" · "}
                        </>
                      )}
                      {"Expires in "}
                      {formatDuration(oauthStatus.expires_in_seconds)}
                      {oauthStatus.scopes && oauthStatus.scopes.length > 0 && (
                        <> · {oauthStatus.scopes.join(", ")}</>
                      )}
                    </p>
                  )}
                {/* Show API key info if also configured with a key */}
                {isConfigured && credential && provider.supportsApiKey && (
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    API key: <code className="font-mono">{credential.value_masked}</code>
                  </p>
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
            {/* OAuth providers (except Claude which is CLI-managed) */}
            {isOAuth && !isClaude && (
              <>
                {(normalized === "missing" || normalized === "expired") && (
                  <button
                    onClick={onOAuthStart}
                    disabled={isOAuthLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-50 dark:bg-blue-950/30 hover:bg-blue-100 dark:hover:bg-blue-900/30 text-blue-700 dark:text-blue-300 transition-colors disabled:opacity-50"
                  >
                    {isOAuthLoading ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <ExternalLink className="h-3.5 w-3.5" />
                    )}
                    {normalized === "expired" ? "Re-authenticate" : "Authenticate"}
                  </button>
                )}
                {/* For providers that also support API keys, show Add Key option */}
                {provider.supportsApiKey && !isConfigured && (
                  <button
                    onClick={onAdd}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 transition-colors"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Add Key
                  </button>
                )}
              </>
            )}

            {/* Non-OAuth providers (and API key management for dual-mode providers) */}
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
