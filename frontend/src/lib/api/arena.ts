import type { ArenaOverview } from '@/app/arena/types'
import { fetchApi } from '@/lib/api-config'

export async function fetchArenaOverview(
  days = 30,
  projectId = 'agent-hub',
  primaryAgentSlug = 'persona',
): Promise<ArenaOverview> {
  const params = new URLSearchParams()
  params.set('days', String(days))
  params.set('project_id', projectId)
  params.set('primary_agent_slug', primaryAgentSlug)

  const res = await fetchApi(`/api/arena/overview?${params}`)
  if (!res.ok) {
    throw new Error('Failed to fetch Arena overview')
  }
  return res.json()
}
