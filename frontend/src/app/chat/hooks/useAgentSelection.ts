import { useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { fetchApi, getApiBaseUrl } from '@/lib/api-config'
import type { Agent } from '@/types/agent'

interface UseAgentSelectionReturn {
  agents: Agent[]
  selectedAgent: Agent | null
  setSelectedAgent: (agent: Agent | null) => void
  loading: boolean
  error: string | null
}

export function useAgentSelection(): UseAgentSelectionReturn {
  const searchParams = useSearchParams()
  // Extract agent slug once — only this value should trigger a re-fetch,
  // not other search param changes (e.g. session_id from replaceState).
  const agentSlugFromUrl = searchParams.get('agent')

  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchAgents = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await fetchApi(
          `${getApiBaseUrl()}/api/agents?active_only=true`,
        )
        if (!res.ok) throw new Error(`Failed to fetch agents: ${res.status}`)
        const data = await res.json()
        const fetchedAgents = data.agents
        setAgents(fetchedAgents)

        // URL agent selection should win even after the user has used another agent.
        setSelectedAgent((currentAgent) => {
          if (agentSlugFromUrl) {
            const urlAgent = fetchedAgents.find(
              (a: Agent) => a.slug === agentSlugFromUrl,
            )
            if (urlAgent && currentAgent?.slug !== urlAgent.slug)
              return urlAgent
          }

          if (!currentAgent && fetchedAgents.length > 0) {
            return (
              fetchedAgents.find((a: Agent) => a.slug === 'chat') ||
              fetchedAgents[0]
            )
          }

          return currentAgent
        })
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load agents')
      } finally {
        setLoading(false)
      }
    }
    fetchAgents()
  }, [agentSlugFromUrl])

  return {
    agents,
    selectedAgent,
    setSelectedAgent,
    loading,
    error,
  }
}
