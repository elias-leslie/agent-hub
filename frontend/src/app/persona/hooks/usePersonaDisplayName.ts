'use client'

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { fetchPersona, PERSONA_QUERY_KEY } from '@/lib/api/persona'
import {
  getPersonaDisplayName,
  getPersonaPossessive,
} from '../utils/displayName'

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
  const personaPossessive = useMemo(
    () => getPersonaPossessive(query.data?.name),
    [query.data?.name],
  )

  return {
    ...query,
    persona: query.data ?? null,
    personaName,
    personaPossessive,
  }
}
