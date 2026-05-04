import type {
  PersonaImprovementDashboard,
  PersonaImprovementSchedule,
  PersonaImprovementScheduleUpdate,
} from '@/app/persona/analytics/types'
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

export async function updatePersonaImprovementSchedule(
  payload: PersonaImprovementScheduleUpdate,
): Promise<PersonaImprovementSchedule> {
  const res = await fetchApi('/api/persona/improvement/schedule', {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => null)
    throw new Error(
      error?.detail ?? 'Failed to update persona improvement schedule',
    )
  }
  return res.json()
}
