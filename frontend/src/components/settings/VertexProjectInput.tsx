'use client'

import { Check, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

interface VertexProjectInputProps {
  value: string
  onSave: (project: string) => void
}

export function VertexProjectInput({ value, onSave }: VertexProjectInputProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  useEffect(() => {
    setDraft(value)
  }, [value])

  function handleSave() {
    onSave(draft.trim())
    setEditing(false)
  }

  if (!editing) {
    return (
      <div className="flex items-center gap-1 mt-1">
        <span className="text-[10px] text-slate-500">Vertex AI project:</span>
        {value ? (
          <code className="text-[10px] font-mono text-slate-400">{value}</code>
        ) : (
          <span className="text-[10px] text-red-400">
            not set (required for OAuth)
          </span>
        )}
        <button
          onClick={() => setEditing(true)}
          className="ml-1 text-[10px] text-amber-500 hover:text-amber-500 font-medium"
        >
          {value ? 'edit' : 'set'}
        </button>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1 mt-1">
      <span className="text-[10px] text-slate-500">Project:</span>
      <input
        ref={inputRef}
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') handleSave()
          if (e.key === 'Escape') setEditing(false)
        }}
        placeholder="gen-lang-client-..."
        className="px-1.5 py-0.5 text-[10px] font-mono rounded border border-slate-600 bg-slate-800 text-slate-100 focus:outline-none focus:ring-1 focus:ring-amber-500 w-48"
      />
      <button
        onClick={handleSave}
        className="p-0.5 rounded text-green-500 hover:bg-green-950/30 cursor-pointer"
      >
        <Check className="h-3 w-3" />
      </button>
      <button
        onClick={() => setEditing(false)}
        className="p-0.5 rounded text-slate-400 hover:bg-slate-800"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  )
}
