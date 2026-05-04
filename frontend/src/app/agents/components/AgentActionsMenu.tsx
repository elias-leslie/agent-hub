import { Archive, Copy, MessageSquare, MoreVertical } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useId, useRef, useState } from 'react'
import type { Agent } from '../lib/types'

export function AgentActionsMenu({
  agent,
  onClone,
  onArchive,
}: {
  agent: Agent
  onClone?: (agent: Agent) => void
  onArchive?: (agent: Agent) => void
}) {
  const [open, setOpen] = useState(false)
  const menuId = useId()
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) {
      return
    }

    const handlePointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-label={`Open actions for ${agent.name}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        className="p-1.5 rounded hover:bg-slate-800 transition-colors"
      >
        <MoreVertical className="h-4 w-4 text-slate-400" />
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={`${agent.name} actions`}
          className="absolute right-0 top-8 z-50 w-40 rounded-lg border border-slate-700 bg-slate-800 py-1 shadow-lg"
        >
          <Link
            href={`/agents/${agent.slug}/chat`}
            role="menuitem"
            onClick={() => setOpen(false)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-slate-700"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            Chat
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              onClone?.(agent)
              setOpen(false)
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-slate-700"
          >
            <Copy className="h-3.5 w-3.5" />
            Clone
          </button>
          <div className="my-1 border-t border-slate-700" />
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              onArchive?.(agent)
              setOpen(false)
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-red-600 hover:bg-red-950/20"
          >
            <Archive className="h-3.5 w-3.5" />
            Archive
          </button>
        </div>
      )}
    </div>
  )
}
