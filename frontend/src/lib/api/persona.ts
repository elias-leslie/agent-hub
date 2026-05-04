import { fetchApi } from '@/lib/api-config'
import type { Persona } from '@/types/persona'

export const PERSONA_QUERY_KEY = ['persona'] as const

export async function fetchPersona(): Promise<Persona> {
  const response = await fetchApi('/api/persona')
  if (!response.ok) {
    throw new Error(`Failed to fetch persona: ${response.status}`)
  }
  return response.json()
}
