'use client'

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { fetchPersona, PERSONA_QUERY_KEY } from '@/lib/api/persona'

export function getPersonaDisplayName(name?: string | null): string {
  const trimmed = name?.trim()
  return trimmed && trimmed.length > 0 ? trimmed : 'Persona'
}

/** Resolves the persona display name from the persona row (`/api/persona`). */
export function usePersonaDisplayName() {
  const query = useQuery({
    queryKey: PERSONA_QUERY_KEY,
    queryFn: fetchPersona,
    staleTime: 60000,
  })

  const personaName = useMemo(
    () => getPersonaDisplayName(query.data?.name),
    [query.data?.name],
  )

  return {
    ...query,
    persona: query.data ?? null,
    personaName,
  }
}
