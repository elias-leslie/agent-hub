/**
 * Memory settings API client.
 *
 * Provides functions for managing memory system configuration
 * including enable/disable toggle and token budget settings.
 */

import { getApiBaseUrl, fetchApi } from "../api-config";

const API_BASE = `${getApiBaseUrl()}/api`;

export interface MemorySettings {
  enabled: boolean; // Kill switch for memory injection
  budget_enabled: boolean; // Budget enforcement toggle
  total_budget: number; // Total token budget
  max_mandates: number; // Per-tier count limit (0 = unlimited)
  max_guardrails: number; // Per-tier count limit (0 = unlimited)
  reference_index_enabled: boolean; // TOON reference index toggle
  continuity_enabled: boolean; // Recent Activity block toggle
  continuity_max_sessions: number; // Max sessions in Recent Activity
}

export interface BudgetUsage {
  mandates_tokens: number;
  guardrails_tokens: number;
  reference_tokens: number;
  continuity_tokens: number;
  total_tokens: number;
  total_budget: number;
  remaining: number;
  hit_limit: boolean;
  // Count fields for coverage tracking
  mandates_injected: number;
  mandates_total: number;
  guardrails_injected: number;
  guardrails_total: number;
  reference_injected: number;
  reference_total: number;
}

export interface LLMConfig {
  reranker_model: string;
  embedding_model: string;
}

/**
 * Get LLM configuration for memory system.
 */
export async function getLLMConfig(): Promise<LLMConfig> {
  const response = await fetchApi(`${API_BASE}/memory/llm-config`);
  if (!response.ok) {
    throw new Error(`Failed to get LLM config: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Get current memory settings.
 */
export async function getSettings(): Promise<MemorySettings> {
  const response = await fetchApi(`${API_BASE}/memory/settings`);
  if (!response.ok) {
    throw new Error(`Failed to get settings: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Update memory settings.
 */
export async function updateSettings(
  settings: Partial<MemorySettings>
): Promise<MemorySettings> {
  const response = await fetchApi(`${API_BASE}/memory/settings`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(settings),
  });
  if (!response.ok) {
    throw new Error(`Failed to update settings: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Get budget usage statistics.
 */
export async function getBudgetUsage(): Promise<BudgetUsage> {
  const response = await fetchApi(`${API_BASE}/memory/budget-usage`);
  if (!response.ok) {
    throw new Error(`Failed to get budget usage: ${response.statusText}`);
  }
  return response.json();
}
