import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import {
  buildAgentUpdatePayload,
  createAgentFormData,
} from '@/app/agents/[slug]/agent-form'
import type { Agent } from '@/app/agents/[slug]/types'
import { usePersona } from '@/app/persona/hooks/usePersona'
import { fetchAgent, fetchModels, updateAgent } from '@/lib/api'

const PERSONA_SLUG = 'persona'

export function usePersonaSettings() {
  const queryClient = useQueryClient()
  const {
    persona,
    loading: personaLoading,
    error: personaError,
    updatePersona: updatePersonaField,
    setPersona,
    autosave,
  } = usePersona()

  // --- Agent (explicit save) ---
  const {
    data: agent,
    isLoading: agentLoading,
    error: agentQueryError,
  } = useQuery({
    queryKey: ['agent', PERSONA_SLUG],
    queryFn: () => fetchAgent(PERSONA_SLUG),
  })

  const { data: availableModels = [] } = useQuery({
    queryKey: ['models', 'options'],
    queryFn: fetchModels,
  })

  const [agentFormData, setAgentFormData] = useState<Partial<Agent>>({})
  const [hasAgentChanges, setHasAgentChanges] = useState(false)

  useEffect(() => {
    if (agent) {
      setAgentFormData(createAgentFormData(agent))
      setHasAgentChanges(false)
    }
  }, [agent])

  const updateAgentField = useCallback(
    <K extends keyof Agent>(field: K, value: Agent[K]) => {
      setAgentFormData((prev) => ({ ...prev, [field]: value }))
      setHasAgentChanges(true)
    },
    [],
  )

  const saveMutation = useMutation({
    mutationFn: (data: Partial<Agent>) => updateAgent(PERSONA_SLUG, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent', PERSONA_SLUG] })
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      setHasAgentChanges(false)
    },
  })

  const saveAgent = useCallback(() => {
    saveMutation.mutate(buildAgentUpdatePayload(agentFormData))
  }, [saveMutation, agentFormData])

  return {
    // Persona
    persona,
    personaLoading,
    personaError,
    updatePersonaField,
    refreshPersona: setPersona,
    personaAutosave: autosave,

    // Agent
    agent,
    agentLoading,
    agentError:
      agentQueryError instanceof Error
        ? agentQueryError.message
        : agentQueryError
          ? 'Failed to load persona agent settings'
          : null,
    agentFormData,
    hasAgentChanges,
    updateAgentField,
    saveAgent,
    isSaving: saveMutation.isPending,
    saveSuccess: saveMutation.isSuccess,
    saveError: saveMutation.isError,

    // Models
    availableModels,
  }
}
