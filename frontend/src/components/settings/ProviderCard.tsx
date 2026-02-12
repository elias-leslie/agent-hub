"use client";

import { Plus, Pencil, Trash2, Check, X, Loader2, Shield } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Credential } from "@/lib/api";
import { ProviderForm } from "./ProviderForm";

interface ProviderInfo {
  id: string;
  name: string;
  hint: string;
  oauth?: boolean;
}

interface OAuthStatus {
  status: "valid" | "expired" | "missing";
  token_prefix?: string | null;
  expires_in_seconds?: number | null;
  scopes?: string[];
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
}: ProviderCardProps) {
  const isConfigured = !!credential;
  const isOAuth = provider.oauth;
  const isFormOpen = isEditing || isAdding;

  return (
    <div
      className={cn(
        "rounded-lg border p-4 transition-colors",
        isConfigured || isOAuth
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
                ? oauthStatus?.status === "valid"
                  ? "bg-green-400"
                  : oauthStatus?.status === "expired"
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
                  {oauthStatus?.status === "valid" && (
                    <span className="text-xs text-green-600 dark:text-green-400">
                      · Active
                    </span>
                  )}
                  {oauthStatus?.status === "expired" && (
                    <span className="text-xs text-red-500">
                      · Expired — run `claude` to re-auth
                    </span>
                  )}
                  {oauthStatus?.status === "missing" && (
                    <span className="text-xs text-slate-500">
                      · Not authenticated
                    </span>
                  )}
                </div>
                {oauthStatus?.status === "valid" &&
                  oauthStatus.expires_in_seconds != null && (
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      <code className="font-mono text-[10px]">
                        {oauthStatus.token_prefix}
                      </code>
                      {" · Expires in "}
                      {formatDuration(oauthStatus.expires_in_seconds)}
                      {oauthStatus.scopes && oauthStatus.scopes.length > 0 && (
                        <> · {oauthStatus.scopes.join(", ")}</>
                      )}
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

        {!isOAuth && !isFormOpen && (
          <div className="flex items-center gap-1">
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
            ) : (
              <button
                onClick={onAdd}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
                Add Key
              </button>
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
