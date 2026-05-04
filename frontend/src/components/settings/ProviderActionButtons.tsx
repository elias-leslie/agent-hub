'use client'

import {
  Check,
  ExternalLink,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  Unplug,
  X,
} from 'lucide-react'
import type { Credential } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { ProviderInfo } from './constants'

interface ProviderActionButtonsProps {
  provider: ProviderInfo
  credentials: Credential[]
  isConfigured: boolean
  isOAuth: boolean
  isConfirmDelete: boolean
  isDeletingThis: boolean
  hasOAuthToken: boolean
  onEdit: () => void
  onAdd: () => void
  onDeleteAll: (ids: number[]) => void
  onConfirmDelete: () => void
  onCancelDelete: () => void
  onOAuthStart?: () => void
  onDisconnectOAuth?: () => void
  isOAuthLoading?: boolean
  isConfirmDisconnectOAuth?: boolean
  onRequestDisconnectOAuth?: () => void
  onCancelDisconnectOAuth?: () => void
}

export function ProviderActionButtons({
  provider,
  credentials,
  isConfigured,
  isOAuth,
  isConfirmDelete,
  isDeletingThis,
  hasOAuthToken,
  onEdit,
  onAdd,
  onDeleteAll,
  onConfirmDelete,
  onCancelDelete,
  onOAuthStart,
  onDisconnectOAuth,
  isOAuthLoading,
  isConfirmDisconnectOAuth = false,
  onRequestDisconnectOAuth,
  onCancelDisconnectOAuth,
}: ProviderActionButtonsProps) {
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {isOAuth && onOAuthStart && (
        <OAuthButton
          isOAuthLoading={isOAuthLoading}
          hasOAuthToken={hasOAuthToken}
          onOAuthStart={onOAuthStart}
        />
      )}
      {isOAuth &&
        hasOAuthToken &&
        onDisconnectOAuth &&
        (isConfirmDisconnectOAuth ? (
          <div className="flex items-center gap-1">
            <span className="text-xs text-red-500 mr-1">Disconnect OAuth?</span>
            <button
              onClick={onDisconnectOAuth}
              aria-label="Confirm disconnect OAuth"
              className="p-1.5 rounded-md bg-red-500 hover:bg-red-600 text-white transition-colors"
            >
              <Check className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={onCancelDisconnectOAuth}
              aria-label="Cancel disconnect OAuth"
              className="p-1.5 rounded-md hover:bg-slate-800 text-slate-500 transition-colors"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : (
          <button
            onClick={onRequestDisconnectOAuth}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-950/30 hover:bg-red-900/30 text-red-300 transition-colors cursor-pointer"
          >
            <Unplug className="h-3.5 w-3.5" />
            Disconnect
          </button>
        ))}

      <ApiKeyActions
        provider={provider}
        credentials={credentials}
        isConfigured={isConfigured}
        isConfirmDelete={isConfirmDelete}
        isDeletingThis={isDeletingThis}
        onEdit={onEdit}
        onAdd={onAdd}
        onDeleteAll={onDeleteAll}
        onConfirmDelete={onConfirmDelete}
        onCancelDelete={onCancelDelete}
      />
    </div>
  )
}

interface OAuthButtonProps {
  isOAuthLoading?: boolean
  hasOAuthToken: boolean
  onOAuthStart: () => void
}

function OAuthButton({
  isOAuthLoading,
  hasOAuthToken,
  onOAuthStart,
}: OAuthButtonProps) {
  return (
    <button
      onClick={onOAuthStart}
      disabled={isOAuthLoading}
      className={cn(
        'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50',
        hasOAuthToken
          ? 'bg-slate-800 hover:bg-slate-700 text-slate-400'
          : 'bg-blue-950/30 hover:bg-blue-900/30 text-amber-300',
      )}
    >
      {isOAuthLoading ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <ExternalLink className="h-3.5 w-3.5" />
      )}
      {hasOAuthToken ? 'Re-auth' : 'Authenticate'}
    </button>
  )
}

interface ApiKeyActionsProps {
  provider: ProviderInfo
  credentials: Credential[]
  isConfigured: boolean
  isConfirmDelete: boolean
  isDeletingThis: boolean
  onEdit: () => void
  onAdd: () => void
  onDeleteAll: (ids: number[]) => void
  onConfirmDelete: () => void
  onCancelDelete: () => void
}

function ApiKeyActions({
  provider,
  credentials,
  isConfigured,
  isConfirmDelete,
  isDeletingThis,
  onEdit,
  onAdd,
  onDeleteAll,
  onConfirmDelete,
  onCancelDelete,
}: ApiKeyActionsProps) {
  if (isConfigured && credentials.length > 0) {
    if (isConfirmDelete) {
      return (
        <div className="flex items-center gap-1">
          <span className="text-xs text-red-500 mr-1">Delete?</span>
          <button
            onClick={() => onDeleteAll(credentials.map((c) => c.id))}
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
            className="p-1.5 rounded-md hover:bg-slate-800 text-slate-500 transition-colors"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )
    }

    return (
      <div className="flex items-center gap-1 flex-wrap">
        {provider.id === 'gemini' && (
          <button
            onClick={onAdd}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Key
          </button>
        )}
        <button
          onClick={onEdit}
          className="p-1.5 rounded-md hover:bg-slate-800 text-slate-400 transition-colors"
          title={provider.id === 'gemini' ? 'Update primary key' : 'Edit key'}
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={onConfirmDelete}
          className="p-1.5 rounded-md hover:bg-red-950/30 text-slate-400 hover:text-red-500 transition-colors"
          title={credentials.length > 1 ? 'Delete all keys' : 'Delete key'}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    )
  }

  // Show "Add Key" for all unconfigured providers (including OAuth providers that also accept API keys)
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <button
        onClick={onAdd}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
      >
        <Plus className="h-3.5 w-3.5" />
        {credentials.length > 0 ? 'Update' : 'Add Key'}
      </button>
      {/* Allow adding multiple keys for single-field providers like Gemini */}
      {credentials.length > 0 && provider.id === 'gemini' && (
        <button
          onClick={onAdd}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
          Add Another Key
        </button>
      )}
    </div>
  )
}
