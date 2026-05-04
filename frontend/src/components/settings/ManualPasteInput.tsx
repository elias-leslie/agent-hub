'use client'

import { Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { MANUAL_PASTE, PROVIDER_ID_CLAUDE } from './ProviderCardUtils'

interface ManualPasteInputProps {
  providerId: string
  onSubmit: (input: string) => Promise<void> | void
  onCancel: () => void
  error?: string | null
}

export function ManualPasteInput({
  providerId,
  onSubmit,
  onCancel,
  error,
}: ManualPasteInputProps) {
  const [value, setValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const isClaude = providerId === PROVIDER_ID_CLAUDE
  const hint = isClaude ? MANUAL_PASTE.CLAUDE_HINT : MANUAL_PASTE.DEFAULT_HINT
  const placeholder = isClaude
    ? MANUAL_PASTE.CLAUDE_PLACEHOLDER
    : MANUAL_PASTE.DEFAULT_PLACEHOLDER

  async function handleSubmit() {
    if (!value.trim() || submitting) return
    setSubmitting(true)
    try {
      await onSubmit(value.trim())
    } finally {
      setSubmitting(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && value.trim()) {
      handleSubmit()
    } else if (e.key === 'Escape') {
      onCancel()
    }
  }

  return (
    <div className="mt-3 space-y-2">
      <p className="text-xs text-slate-400">{hint}</p>
      <div className="flex gap-2">
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={submitting}
          className="flex-1 px-3 py-1.5 text-xs rounded-md border border-slate-600 bg-slate-800 text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500 font-mono disabled:opacity-50"
        />
        <button
          onClick={handleSubmit}
          disabled={!value.trim() || submitting}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-amber-500 hover:bg-amber-400 text-slate-950 transition-colors disabled:opacity-50"
        >
          {submitting && <Loader2 className="h-3 w-3 animate-spin" />}
          Submit
        </button>
        <button
          onClick={onCancel}
          disabled={submitting}
          className="px-3 py-1.5 text-xs font-medium rounded-md bg-slate-800 hover:bg-slate-700 text-slate-400 transition-colors disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  )
}
