"use client";

import { Plus, Pencil, Trash2, Check, X, Loader2, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Credential } from "@/lib/api";
import type { ProviderInfo } from "./constants";

interface ProviderActionButtonsProps {
  provider: ProviderInfo;
  credential?: Credential;
  isConfigured: boolean;
  isOAuth: boolean;
  isConfirmDelete: boolean;
  isDeletingThis: boolean;
  hasOAuthToken: boolean;
  onEdit: () => void;
  onAdd: () => void;
  onDelete: (id: number) => void;
  onConfirmDelete: () => void;
  onCancelDelete: () => void;
  onOAuthStart?: () => void;
  isOAuthLoading?: boolean;
}

export function ProviderActionButtons({
  provider,
  credential,
  isConfigured,
  isOAuth,
  isConfirmDelete,
  isDeletingThis,
  hasOAuthToken,
  onEdit,
  onAdd,
  onDelete,
  onConfirmDelete,
  onCancelDelete,
  onOAuthStart,
  isOAuthLoading,
}: ProviderActionButtonsProps) {
  return (
    <div className="flex items-center gap-1">
      {isOAuth && onOAuthStart && (
        <OAuthButton
          isOAuthLoading={isOAuthLoading}
          hasOAuthToken={hasOAuthToken}
          onOAuthStart={onOAuthStart}
        />
      )}

      {isOAuth && provider.supportsApiKey && !isConfigured && (
        <button
          onClick={onAdd}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
          Add Key
        </button>
      )}

      {(!isOAuth || (provider.supportsApiKey && isConfigured)) && (
        <ApiKeyActions
          credential={credential}
          isConfigured={isConfigured}
          isOAuth={isOAuth}
          isConfirmDelete={isConfirmDelete}
          isDeletingThis={isDeletingThis}
          onEdit={onEdit}
          onAdd={onAdd}
          onDelete={onDelete}
          onConfirmDelete={onConfirmDelete}
          onCancelDelete={onCancelDelete}
        />
      )}
    </div>
  );
}

interface OAuthButtonProps {
  isOAuthLoading?: boolean;
  hasOAuthToken: boolean;
  onOAuthStart: () => void;
}

function OAuthButton({ isOAuthLoading, hasOAuthToken, onOAuthStart }: OAuthButtonProps) {
  return (
    <button
      onClick={onOAuthStart}
      disabled={isOAuthLoading}
      className={cn(
        "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50",
        hasOAuthToken
          ? "bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-400"
          : "bg-blue-50 dark:bg-blue-950/30 hover:bg-blue-100 dark:hover:bg-blue-900/30 text-blue-700 dark:text-blue-300",
      )}
    >
      {isOAuthLoading ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <ExternalLink className="h-3.5 w-3.5" />
      )}
      {hasOAuthToken ? "Re-auth" : "Authenticate"}
    </button>
  );
}

interface ApiKeyActionsProps {
  credential?: Credential;
  isConfigured: boolean;
  isOAuth: boolean;
  isConfirmDelete: boolean;
  isDeletingThis: boolean;
  onEdit: () => void;
  onAdd: () => void;
  onDelete: (id: number) => void;
  onConfirmDelete: () => void;
  onCancelDelete: () => void;
}

function ApiKeyActions({
  credential,
  isConfigured,
  isOAuth,
  isConfirmDelete,
  isDeletingThis,
  onEdit,
  onAdd,
  onDelete,
  onConfirmDelete,
  onCancelDelete,
}: ApiKeyActionsProps) {
  if (isConfigured && credential) {
    if (isConfirmDelete) {
      return (
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
      );
    }

    return (
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
    );
  }

  if (!isOAuth) {
    return (
      <button
        onClick={onAdd}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 transition-colors"
      >
        <Plus className="h-3.5 w-3.5" />
        Add Key
      </button>
    );
  }

  return null;
}
