'use client'

import { ArrowUp, Check, Pencil, Trash2, X } from 'lucide-react'
import type { Credential } from '@/lib/api'
import type { ProviderInfo } from './constants'

interface CredentialListProps {
  credentials: Credential[]
  provider: ProviderInfo
  isConfigured: boolean
  onEditCredential?: (credentialId: number) => void
  onDeleteCredential?: (credentialId: number) => void
  onSetPrimaryCredential?: (credentialId: number) => void
  pendingCredentialDeleteId?: number | null
  onRequestDeleteCredential?: (credentialId: number) => void
  onCancelDeleteCredential?: () => void
}

export function CredentialList({
  credentials,
  provider,
  isConfigured,
  onEditCredential,
  onDeleteCredential,
  onSetPrimaryCredential,
  pendingCredentialDeleteId,
  onRequestDeleteCredential,
  onCancelDeleteCredential,
}: CredentialListProps) {
  if (!isConfigured || credentials.length === 0) return null

  // Multi-field providers (e.g. Vertex: project + key)
  if (provider.credentialFields) {
    return (
      <div className="space-y-0.5">
        {credentials.map((cred) => {
          const fieldDef = provider.credentialFields?.find(
            (f) => f.credentialType === cred.credential_type,
          )
          return (
            <p
              key={cred.id}
              className="text-[10px] text-slate-500 truncate font-mono"
            >
              {fieldDef?.label ?? cred.credential_type}: {cred.value_masked}
            </p>
          )
        })}
      </div>
    )
  }

  // Single-field providers (supports multiple API keys)
  return (
    <div className="space-y-0.5">
      {credentials.map((cred, idx) => (
        <div
          key={cred.id}
          className="flex items-center gap-1.5 text-[10px] text-slate-500 truncate"
        >
          {credentials.length > 1 && (
            <span className="font-medium text-slate-400">
              {idx === 0 ? 'Primary:' : `Key ${idx + 1}:`}
            </span>
          )}
          <code className="font-mono bg-slate-800 px-1 rounded">
            {cred.value_masked}
          </code>
          {(onEditCredential || onDeleteCredential) && (
            <div className="inline-flex items-center gap-0.5 ml-0.5">
              {onEditCredential && (
                <button
                  onClick={() => onEditCredential(cred.id)}
                  className="p-0.5 rounded hover:bg-slate-800 text-slate-400 transition-colors"
                  title="Update this key"
                >
                  <Pencil className="h-2.5 w-2.5" />
                </button>
              )}
              {onDeleteCredential &&
                (pendingCredentialDeleteId === cred.id ? (
                  <div className="inline-flex items-center gap-0.5">
                    <span className="text-[10px] text-red-500">
                      Delete key?
                    </span>
                    <button
                      onClick={() => onDeleteCredential(cred.id)}
                      aria-label={`Confirm delete credential ${cred.value_masked}`}
                      className="p-0.5 rounded bg-red-500 text-white transition-colors hover:bg-red-600"
                      title="Confirm delete this key"
                    >
                      <Check className="h-2.5 w-2.5" />
                    </button>
                    <button
                      onClick={onCancelDeleteCredential}
                      aria-label={`Cancel delete credential ${cred.value_masked}`}
                      className="p-0.5 rounded hover:bg-slate-800 text-slate-400 transition-colors"
                      title="Cancel delete this key"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => onRequestDeleteCredential?.(cred.id)}
                    aria-label={`Delete credential ${cred.value_masked}`}
                    className="p-0.5 rounded hover:bg-red-950/30 text-slate-400 hover:text-red-500 transition-colors"
                    title="Delete this key"
                  >
                    <Trash2 className="h-2.5 w-2.5" />
                  </button>
                ))}
              {onSetPrimaryCredential && idx > 0 && (
                <button
                  onClick={() => onSetPrimaryCredential(cred.id)}
                  className="p-0.5 rounded hover:bg-blue-950/30 text-slate-400 hover:text-amber-500 transition-colors cursor-pointer"
                  title="Make primary"
                >
                  <ArrowUp className="h-2.5 w-2.5" />
                </button>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
