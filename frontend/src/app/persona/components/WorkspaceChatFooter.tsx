'use client'

import { MessageInput } from '@agent-hub/chat-ui'
import { ArrowDown, Loader2 } from 'lucide-react'

import { fetchApi, getApiBaseUrl, getWsUrl } from '@/lib/api-config'
import { cn } from '@/lib/utils'
import { CommandSurface } from './persona-operator-chrome'

interface WorkspaceChatFooterProps {
  personaDisplayName: string
  responseStatusLabel: string | null
  status: string
  targetProjectId: string
  sessionProjectId: string | null
  threadSessionId?: string | null
  threadSource?: 'draft' | 'session' | null
  isTerminalThread?: boolean
  sendMessage: (
    content: string,
    targetAgents?: string[],
    sessionIdOverride?: string,
  ) => void
  cancelStream: () => void
  preferencesEndpoint: string
  onNewSession: () => void
  compactViewport?: boolean
  jumpToLatestLabel?: string | null
  onJumpToLatest?: () => void
  showNewThread?: boolean
}

export function WorkspaceChatFooter({
  responseStatusLabel,
  status,
  preferencesEndpoint,
  sendMessage,
  cancelStream,
  onNewSession,
  compactViewport = false,
  jumpToLatestLabel = null,
  onJumpToLatest,
  showNewThread = false,
}: WorkspaceChatFooterProps) {
  const statusRowVisible = Boolean(
    responseStatusLabel || jumpToLatestLabel || showNewThread,
  )

  return (
    <div
      data-testid="persona-chat-footer"
      className={cn(
        'border-t border-slate-900/60 bg-slate-950/88 backdrop-blur-md',
        compactViewport ? 'px-3 py-1.5' : 'px-4 py-2',
      )}
    >
      <div className="mx-auto max-w-4xl">
        {statusRowVisible ? (
          <div
            className={cn(
              'mb-1.5 flex items-center gap-3 text-[11px]',
              responseStatusLabel ? 'justify-between' : 'justify-end',
              compactViewport && 'mb-1',
            )}
          >
            {responseStatusLabel ? (
              <div className="flex min-w-0 items-center gap-2 text-amber-400/80">
                <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
                <span className="truncate">{responseStatusLabel}</span>
              </div>
            ) : (
              <span className="min-h-[0.75rem] flex-1" />
            )}
            <div className="flex shrink-0 items-center gap-3">
              {jumpToLatestLabel && onJumpToLatest ? (
                <button
                  type="button"
                  onClick={onJumpToLatest}
                  className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 transition hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/40"
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                  {jumpToLatestLabel}
                </button>
              ) : null}
              {showNewThread ? (
                <button
                  type="button"
                  onClick={onNewSession}
                  className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 transition hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/40"
                >
                  New thread
                </button>
              ) : null}
            </div>
          </div>
        ) : null}

        <CommandSurface className="rounded-lg">
          <div className={compactViewport ? 'px-2 py-2' : 'px-3 py-3'}>
            <MessageInput
              onSend={sendMessage}
              onCancel={cancelStream}
              status={status as Parameters<typeof MessageInput>[0]['status']}
              compact
              voiceWsUrl={getWsUrl(
                '/api/voice/ws?user_id=agent_hub_user&app=agent-hub&mode=transcribe',
              )}
              ttsBaseUrl={getApiBaseUrl() || window.location.origin}
              preferencesEndpoint={preferencesEndpoint}
              fetchFn={fetchApi}
            />
          </div>
        </CommandSurface>
      </div>
    </div>
  )
}
