'use client'

import { ArrowLeft, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { Suspense, useEffect, useState } from 'react'
import { useChatSession } from '@/app/chat/hooks/useChatSession'
import { ChatPanel } from '@/components/chat'
import { fetchApi } from '@/lib/api-config'
import type { Agent } from '@/types/agent'

function AgentChatContent() {
  const params = useParams()
  const slug = params.slug as string

  const [agent, setAgent] = useState<Agent | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const { activeSessionId, handleSessionCreated, handleNewSession } =
    useChatSession({ contextKey: `agent-page:agent-hub:${slug}` })

  useEffect(() => {
    async function fetchAgent() {
      try {
        const res = await fetchApi(`/api/agents/${slug}`)
        if (!res.ok) throw new Error(`Agent not found: ${slug}`)
        const data = await res.json()
        setAgent(data)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load agent')
      } finally {
        setLoading(false)
      }
    }
    fetchAgent()
  }, [slug])

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    )
  }

  if (error || !agent) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-4">
        <p className="text-sm text-slate-500">{error || 'Agent not found'}</p>
        <Link
          href="/agents"
          className="text-sm text-amber-600 hover:text-amber-700 flex items-center gap-1"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to agents
        </Link>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <header className="flex-shrink-0 border-b border-slate-800 bg-slate-900/80 backdrop-blur-lg z-20">
        <div className="flex items-center gap-3 px-4 h-14">
          <Link
            href={`/agents/${slug}`}
            className="p-1.5 rounded-md text-slate-500 hover:bg-slate-800 transition-colors"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <h1 className="text-lg font-semibold text-slate-100">
            Chat with {agent.name}
          </h1>
          <span className="text-xs text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
            {agent.slug}
          </span>
        </div>
      </header>

      {/* Chat */}
      <main className="flex-1 min-h-0">
        <ChatPanel
          key={slug}
          agent={agent}
          agentSlug={slug}
          sessionId={activeSessionId ?? undefined}
          toolsEnabled={true}
          onSessionCreated={handleSessionCreated}
          onClear={handleNewSession}
          projectId="agent-hub"
        />
      </main>
    </div>
  )
}

export default function AgentChatPage() {
  return (
    <Suspense
      fallback={
        <div className="h-full flex items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      }
    >
      <AgentChatContent />
    </Suspense>
  )
}
