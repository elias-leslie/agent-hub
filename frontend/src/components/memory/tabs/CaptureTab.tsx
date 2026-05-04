'use client'

import { Inbox, Loader2, Pause, Play, Radio, Trash2 } from 'lucide-react'
import { CaptureItem } from '@/components/memory/CaptureItem'
import { useMemoryStream } from '@/hooks/use-memory-stream'
import { cn } from '@/lib/utils'

function CaptureEmpty() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="p-4 rounded-full bg-slate-800 mb-4">
        <Inbox className="w-8 h-8 text-slate-500" />
      </div>
      <h3 className="text-lg font-medium text-slate-100 mb-1">No events yet</h3>
      <p className="text-sm text-slate-400 max-w-sm">
        Observations will appear here in real-time as they are captured by
        hooks, agents, and chat sessions.
      </p>
    </div>
  )
}

function CaptureConnecting() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <Loader2 className="w-8 h-8 text-slate-400 animate-spin mb-4" />
      <h3 className="text-lg font-medium text-slate-100 mb-1">
        Connecting to capture stream...
      </h3>
      <p className="text-sm text-slate-400 max-w-sm">
        Establishing SSE connection to the backend.
      </p>
    </div>
  )
}

export function CaptureTab() {
  const { events, isConnected, isPaused, pause, resume, clear } =
    useMemoryStream()

  const showConnecting = !isConnected && !isPaused && events.length === 0

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Header bar */}
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Radio className="h-4 w-4 text-slate-400" />
            <span className="text-sm font-medium text-slate-200">
              Capture Stream
            </span>

            {/* Connection status */}
            <span className="flex items-center gap-1.5 text-xs">
              <span
                className={cn(
                  'w-2 h-2 rounded-full',
                  isConnected
                    ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.4)]'
                    : isPaused
                      ? 'bg-amber-400'
                      : 'bg-red-400',
                )}
              />
              <span className="text-slate-500">
                {isConnected ? 'Live' : isPaused ? 'Paused' : 'Disconnected'}
              </span>
            </span>

            {events.length > 0 && (
              <span className="text-xs text-slate-500">
                {events.length} event{events.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={isPaused ? resume : pause}
              className={cn(
                'inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors',
                isPaused
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20'
                  : 'bg-slate-800 border-slate-700 text-slate-300 hover:text-slate-100 hover:border-slate-600',
              )}
            >
              {isPaused ? (
                <>
                  <Play className="h-3.5 w-3.5" />
                  Resume
                </>
              ) : (
                <>
                  <Pause className="h-3.5 w-3.5" />
                  Pause
                </>
              )}
            </button>

            <button
              onClick={clear}
              disabled={events.length === 0}
              className={cn(
                'inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors',
                events.length === 0
                  ? 'bg-slate-800/50 border-slate-800 text-slate-600 cursor-not-allowed'
                  : 'bg-slate-800 border-slate-700 text-slate-300 hover:text-slate-100 hover:border-slate-600',
              )}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Clear
            </button>
          </div>
        </div>
      </div>

      {/* Event list */}
      <div className="flex-1 overflow-auto">
        {showConnecting ? (
          <CaptureConnecting />
        ) : events.length === 0 ? (
          <CaptureEmpty />
        ) : (
          <div className="p-4 lg:p-6 space-y-0.5 max-w-3xl">
            {events.map((event) => (
              <CaptureItem key={event.id} event={event} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
