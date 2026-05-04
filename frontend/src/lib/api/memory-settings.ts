/**
 * Memory settings API client.
 *
 * Provides functions for managing memory system configuration
 * including enable/disable toggle and continuity settings.
 */

import { fetchApi, getApiBaseUrl } from '../api-config'

const API_BASE = `${getApiBaseUrl()}/api`

export interface MemorySettings {
  enabled: boolean // Kill switch for memory injection
  continuity_enabled: boolean // Recent Activity block toggle
  continuity_max_sessions: number // Max sessions in Recent Activity
  active_variant: 'BASELINE' | 'ENHANCED' | 'MINIMAL' | 'AGGRESSIVE' | null
}

export interface MemoryBudgetUsage {
  mandates_tokens: number
  guardrails_tokens: number
  reference_tokens: number
  continuity_tokens: number
  total_tokens: number
  // Count fields for coverage tracking
  mandates_injected: number
  mandates_total: number
  guardrails_injected: number
  guardrails_total: number
  reference_injected: number
  reference_total: number
}

export interface LLMConfig {
  reranker_model: string
  embedding_model: string
}

/**
 * Get LLM configuration for memory system.
 */
export async function getLLMConfig(): Promise<LLMConfig> {
  const response = await fetchApi(`${API_BASE}/memory/llm-config`)
  if (!response.ok) {
    throw new Error(`Failed to get LLM config: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Get current memory settings.
 */
export async function getSettings(): Promise<MemorySettings> {
  const response = await fetchApi(`${API_BASE}/memory/settings`)
  if (!response.ok) {
    throw new Error(`Failed to get settings: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Update memory settings.
 */
export async function updateSettings(
  settings: Partial<MemorySettings>,
): Promise<MemorySettings> {
  const response = await fetchApi(`${API_BASE}/memory/settings`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(settings),
  })
  if (!response.ok) {
    throw new Error(`Failed to update settings: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Get current rendered memory usage statistics.
 */
export async function getBudgetUsage(): Promise<MemoryBudgetUsage> {
  const response = await fetchApi(`${API_BASE}/memory/budget-usage`)
  if (!response.ok) {
    throw new Error(`Failed to get budget usage: ${response.statusText}`)
  }
  return response.json()
}
