'use client'

import { Loader2 } from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import { Suspense, useCallback, useEffect, useState } from 'react'

import { ChatPanel } from '@/components/chat'
import {
  type EmbedInboundMessage,
  isEmbedded,
  listenForHostMessages,
  sendToHost,
} from '@/lib/embed/postmessage-bridge'

function EmbedContent() {
  const searchParams = useSearchParams()

  // Initialize from URL params (fallback for simple integrations)
  const [agentSlug, setAgentSlug] = useState(
    () =>
      searchParams.get('agent') || searchParams.get('agentSlug') || 'persona',
  )
  const [projectId, setProjectId] = useState(
    () =>
      searchParams.get('project') ||
      searchParams.get('projectId') ||
      'agent-hub',
  )
  const [sessionId, setSessionId] = useState<string | undefined>(
    () => searchParams.get('session') || undefined,
  )

  const handleSessionCreated = useCallback((id: string) => {
    setSessionId(id)
    sendToHost({ type: 'session_created', payload: { sessionId: id } })
  }, [])

  // Listen for postMessage commands from host
  useEffect(() => {
    const allowedOrigins = searchParams.get('allowedOrigins')?.split(',') || []

    const cleanup = listenForHostMessages(
      (msg: EmbedInboundMessage) => {
        switch (msg.type) {
          case 'set_agent':
            setAgentSlug(msg.payload.agentSlug)
            break
          case 'set_project':
            setProjectId(msg.payload.projectId)
            break
          case 'set_session':
            setSessionId(msg.payload.sessionId)
            break
          case 'send_message':
            // Handled by dispatching to ChatPanel via ref (future enhancement)
            break
        }
      },
      allowedOrigins.length > 0 ? allowedOrigins : undefined,
    )

    // Notify host that embed is ready
    if (isEmbedded()) {
      sendToHost({ type: 'ready' })
    }

    return cleanup
  }, [searchParams])

  return (
    <div className="h-full flex flex-col">
      <ChatPanel
        key={`${projectId}-${agentSlug}`}
        agentSlug={agentSlug}
        sessionId={sessionId}
        toolsEnabled={true}
        onSessionCreated={handleSessionCreated}
        projectId={projectId}
      />
    </div>
  )
}

export default function EmbedPage() {
  return (
    <Suspense
      fallback={
        <div className="h-full flex items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      }
    >
      <EmbedContent />
    </Suspense>
  )
}
