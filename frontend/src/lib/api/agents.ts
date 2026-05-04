// ─────────────────────────────────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────────────────────────────────

import type {
  AgentBenchmarkDashboard,
  AgentBenchmarkRunDetail,
} from '@/app/agents/[slug]/analytics/types'
import type {
  AgentListResponse,
  AgentMetrics,
  AgentMetricsResponse,
} from '@/app/agents/lib/types'
import { fetchApi } from '@/lib/api-config'

export async function fetchAgents(
  activeOnly = true,
): Promise<AgentListResponse> {
  const params = new URLSearchParams()
  params.set('active_only', String(activeOnly))

  const res = await fetchApi(`/api/agents?${params}`)
  if (!res.ok) {
    throw new Error('Failed to fetch agents')
  }
  return res.json()
}

export async function fetchAgentMetrics(): Promise<AgentMetricsResponse>
export async function fetchAgentMetrics(slug: string): Promise<AgentMetrics>
export async function fetchAgentMetrics(
  slug?: string,
): Promise<AgentMetricsResponse | AgentMetrics> {
  const res = await fetchApi(
    slug ? `/api/agents/${slug}/metrics` : '/api/agents/metrics/all',
  )
  if (!res.ok) {
    if (slug) {
      throw new Error('Failed to fetch agent metrics')
    }

    // Return empty metrics on error - don't fail the whole page
    return { metrics: {} }
  }
  return res.json()
}

export async function fetchAgentBenchmarkDashboard(
  slug: string,
  days = 30,
  limit = 20,
): Promise<AgentBenchmarkDashboard> {
  const params = new URLSearchParams()
  params.set('days', String(days))
  params.set('limit', String(limit))

  const res = await fetchApi(`/api/agents/${slug}/benchmarks?${params}`)
  if (!res.ok) {
    throw new Error('Failed to fetch benchmark dashboard')
  }
  return res.json()
}

export async function fetchAgentBenchmarkRunDetail(
  slug: string,
  runId: string,
): Promise<AgentBenchmarkRunDetail> {
  const res = await fetchApi(`/api/agents/${slug}/benchmarks/${runId}`)
  if (!res.ok) {
    throw new Error('Failed to fetch benchmark run details')
  }
  return res.json()
}
