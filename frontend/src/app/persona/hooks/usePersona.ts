import { useCallback, useEffect, useState } from 'react'
import { useToastActions } from '@/components/error/toast'
import { fetchPersona as fetchPersonaRecord } from '@/lib/api/persona'
import { buildApiUrl, fetchApi } from '@/lib/api-config'
import type { Persona, PersonaUpdate } from '@/types/persona'
import { useDebouncedAutosave } from './useDebouncedAutosave'

export interface PersonaAutosaveState {
  status: 'idle' | 'scheduled' | 'saving' | 'saved' | 'error'
  errorMessage: string | null
  savedAt: number | null
}

interface UsePersonaReturn {
  persona: Persona | null
  loading: boolean
  error: string | null
  updatePersona: (fields: PersonaUpdate) => void
  setPersona: React.Dispatch<React.SetStateAction<Persona | null>>
  autosave: PersonaAutosaveState
}

export function usePersona(): UsePersonaReturn {
  const [persona, setPersona] = useState<Persona | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [autosave, setAutosave] = useState<PersonaAutosaveState>({
    status: 'idle',
    errorMessage: null,
    savedAt: null,
  })
  const toast = useToastActions()

  useEffect(() => {
    let cancelled = false
    async function loadPersona() {
      try {
        const data = await fetchPersonaRecord()
        if (!cancelled) {
          setPersona(data)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : 'Failed to load persona',
          )
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadPersona()
    return () => {
      cancelled = true
    }
  }, [])

  const updatePersona = useDebouncedAutosave<Persona, PersonaUpdate>({
    save: async (fields) => {
      setAutosave((prev) => ({
        ...prev,
        status: 'saving',
        errorMessage: null,
      }))
      const res = await fetchApi(buildApiUrl('/api/persona'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
      })
      if (!res.ok) throw new Error(`Failed to update persona: ${res.status}`)
      return res.json()
    },
    onSuccess: (updated) => {
      setPersona(updated)
      setError(null)
      setAutosave({
        status: 'saved',
        errorMessage: null,
        savedAt: Date.now(),
      })
    },
    onError: (err) => {
      console.error('Failed to save persona:', err)
      setAutosave({
        status: 'error',
        errorMessage:
          err instanceof Error
            ? err.message
            : 'Failed to save persona settings',
        savedAt: null,
      })
      toast.error('Failed to save persona settings')
    },
  })

  const handleUpdatePersona = useCallback(
    (fields: PersonaUpdate) => {
      setPersona((prev) => (prev ? { ...prev, ...fields } : prev))
      setAutosave((prev) => ({
        ...prev,
        status: 'scheduled',
        errorMessage: null,
      }))
      updatePersona(fields)
    },
    [updatePersona],
  )

  return {
    persona,
    loading,
    error,
    updatePersona: handleUpdatePersona,
    setPersona,
    autosave,
  }
}
