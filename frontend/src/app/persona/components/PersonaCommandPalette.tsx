'use client'

import { Command } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { cn } from '@/lib/utils'

export interface PersonaCommandItem {
  id: string
  label: string
  description: string
  run: () => void
}

interface PersonaCommandPaletteProps {
  open: boolean
  onClose: () => void
  commands: PersonaCommandItem[]
}

export function PersonaCommandPalette({
  open,
  onClose,
  commands,
}: PersonaCommandPaletteProps) {
  const [query, setQuery] = useState('')

  useEffect(() => {
    if (!open) {
      setQuery('')
      return
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose, open])

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) {
      return commands
    }
    return commands.filter((command) =>
      `${command.label} ${command.description}`
        .toLowerCase()
        .includes(normalized),
    )
  }, [commands, query])

  if (!open) {
    return null
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/60 px-4 pt-[12vh] backdrop-blur-sm">
      <div className="w-full max-w-2xl overflow-hidden rounded-[28px] border border-slate-800 bg-slate-900 shadow-2xl">
        <div className="border-b border-slate-800 px-4 py-3">
          <div className="flex items-center gap-3 rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2">
            <Command className="h-4 w-4 text-slate-500" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Find operator command..."
              className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-600"
            />
          </div>
        </div>
        <div className="max-h-[60vh] overflow-y-auto p-2">
          {filtered.map((command) => (
            <button
              key={command.id}
              type="button"
              onClick={() => {
                command.run()
                onClose()
              }}
              className={cn(
                'flex w-full items-start justify-between gap-3 rounded-2xl px-3 py-3 text-left transition hover:bg-slate-800/80',
              )}
            >
              <div>
                <div className="text-sm font-medium text-slate-100">
                  {command.label}
                </div>
                <div className="mt-1 text-sm text-slate-400">
                  {command.description}
                </div>
              </div>
            </button>
          ))}
          {filtered.length === 0 ? (
            <div className="px-3 py-6 text-sm text-slate-500">
              No commands match.
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
