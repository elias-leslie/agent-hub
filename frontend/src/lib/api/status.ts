/**
 * Status and provider health API
 */

import { fetchApi, getApiBaseUrl } from '../api-config'

const API_BASE = `${getApiBaseUrl()}/api`

export interface ProviderHealthDetails {
  state: 'healthy' | 'degraded' | 'unavailable' | 'unknown'
  latency_ms: number
  error_rate: number
  availability: number
  consecutive_failures: number
  last_check: number | null
  last_success: number | null
  last_error: string | null
}

export interface ProviderStatus {
  name: string
  available: boolean
  configured: boolean
  error: string | null
  health: ProviderHealthDetails | null
}

export interface CircuitBreakerStatus {
  state: string
  consecutive_failures: number
  last_error_signature: string | null
  cooldown_until: number | null
}

export interface StatusResponse {
  status: 'healthy' | 'degraded'
  service: string
  database: string
  providers: ProviderStatus[]
  uptime_seconds: number
  circuit_breakers: Record<string, CircuitBreakerStatus> | null
  thrashing_events_total: number
  circuit_breaker_trips_total: number
}

export async function fetchStatus(): Promise<StatusResponse> {
  const response = await fetchApi(`${API_BASE}/status`)
  if (!response.ok) {
    throw new Error(`Status fetch failed: ${response.status}`)
  }
  return response.json()
}
