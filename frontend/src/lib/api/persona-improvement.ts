import type { PersonaImprovementDashboard } from '@/app/persona/analytics/types'
import { fetchApi } from '@/lib/api-config'

export async function fetchPersonaImprovementDashboard(
  days = 30,
  limit = 8,
): Promise<PersonaImprovementDashboard> {
  const params = new URLSearchParams()
  params.set('days', String(days))
  params.set('limit', String(limit))

  const res = await fetchApi(`/api/persona/improvement?${params}`)
  if (!res.ok) {
    throw new Error('Failed to fetch persona improvement dashboard')
  }
  return res.json()
}
