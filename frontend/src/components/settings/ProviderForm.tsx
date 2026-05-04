'use client'

import { Check, Eye, EyeOff, Loader2 } from 'lucide-react'
import { useState } from 'react'
import type { CredentialField } from './constants'
import type { SaveCredentialOptions } from './ProviderCardTypes'

interface ProviderFormProps {
  providerName: string
  onSave: (value: string, options?: SaveCredentialOptions) => void
  onCancel: () => void
  isSaving: boolean
  error: string | null
  /** When set, renders multiple credential fields instead of a single API key input. */
  credentialFields?: CredentialField[]
  /** Callback for saving multiple credential fields at once. */
  onSaveMulti?: (fields: Record<string, string>) => void
  saveOptions?: SaveCredentialOptions
}

export function ProviderForm({
  providerName,
  onSave,
  onCancel,
  isSaving,
  error,
  credentialFields,
  onSaveMulti,
  saveOptions,
}: ProviderFormProps) {
  const [keyValue, setKeyValue] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  // Multi-field state
  const [multiValues, setMultiValues] = useState<Record<string, string>>(() => {
    if (!credentialFields) return {}
    return Object.fromEntries(
      credentialFields.map((f) => [f.credentialType, '']),
    )
  })

  function handleSave() {
    if (credentialFields && onSaveMulti) {
      // All fields must have values
      const allFilled = credentialFields.every((f) =>
        multiValues[f.credentialType]?.trim(),
      )
      if (!allFilled) return
      const trimmed = Object.fromEntries(
        Object.entries(multiValues).map(([k, v]) => [k, v.trim()]),
      )
      onSaveMulti(trimmed)
    } else {
      if (!keyValue.trim()) return
      onSave(keyValue.trim(), saveOptions)
    }
  }

  const allFilled = credentialFields
    ? credentialFields.every((f) => multiValues[f.credentialType]?.trim())
    : !!keyValue.trim()

  // Multi-field form
  if (credentialFields) {
    return (
      <div className="mt-3 pt-3 border-t border-slate-700 space-y-2">
        {credentialFields.map((field) => (
          <div key={field.credentialType} className="flex items-center gap-2">
            <label className="text-xs text-slate-400 w-20 shrink-0">
              {field.label}
            </label>
            <div className="relative flex-1">
              <input
                type={showPassword ? 'text' : 'password'}
                value={multiValues[field.credentialType] || ''}
                onChange={(e) =>
                  setMultiValues((prev) => ({
                    ...prev,
                    [field.credentialType]: e.target.value,
                  }))
                }
                placeholder={field.placeholder}
                className="w-full px-3 py-2 pr-9 rounded-lg border border-slate-600 bg-slate-800 text-sm text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSave()
                  if (e.key === 'Escape') onCancel()
                }}
              />
            </div>
          </div>
        ))}
        <div className="flex items-center gap-2 justify-end pt-1">
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            aria-label={showPassword ? 'Hide password' : 'Show password'}
            className="p-1 text-slate-400 hover:text-slate-300"
          >
            {showPassword ? (
              <EyeOff className="h-3.5 w-3.5" />
            ) : (
              <Eye className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            onClick={handleSave}
            disabled={!allFilled || isSaving}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-amber-500 hover:bg-amber-400 text-slate-950 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSaving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Check className="h-3.5 w-3.5" />
            )}
            Save
          </button>
          <button
            onClick={onCancel}
            className="px-3 py-2 rounded-lg text-xs font-medium hover:bg-slate-800 text-slate-500 transition-colors"
          >
            Cancel
          </button>
        </div>
        {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
      </div>
    )
  }

  // Single-field form (original)
  return (
    <div className="mt-3 pt-3 border-t border-slate-700">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <input
            type={showPassword ? 'text' : 'password'}
            value={keyValue}
            onChange={(e) => setKeyValue(e.target.value)}
            placeholder={`Enter ${providerName} API key`}
            className="w-full px-3 py-2 pr-9 rounded-lg border border-slate-600 bg-slate-800 text-sm text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500"
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSave()
              if (e.key === 'Escape') onCancel()
            }}
          />
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            aria-label={showPassword ? 'Hide password' : 'Show password'}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-300"
          >
            {showPassword ? (
              <EyeOff className="h-3.5 w-3.5" />
            ) : (
              <Eye className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
        <button
          onClick={handleSave}
          disabled={!keyValue.trim() || isSaving}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-amber-500 hover:bg-amber-400 text-slate-950 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSaving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Check className="h-3.5 w-3.5" />
          )}
          Save
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-2 rounded-lg text-xs font-medium hover:bg-slate-800 text-slate-500 transition-colors"
        >
          Cancel
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
    </div>
  )
}
