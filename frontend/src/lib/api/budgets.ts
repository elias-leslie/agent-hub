/**
 * Budget management API module.
 *
 * Provides functions for fetching per-project cost budget usage
 * and updating budget settings via the permissions endpoint.
 */

import { buildApiUrl, fetchApi } from '../api-config'

export interface BudgetUsage {
  used: number
  limit: number | null
  remaining: number | null
}

export interface ProjectBudget {
  project_id: string
  daily: BudgetUsage
  monthly: BudgetUsage
  alert_level: 'warning' | 'critical' | null
}

export interface BudgetSettingsUpdate {
  daily_cost_budget_usd?: number | null
  monthly_cost_budget_usd?: number | null
  budget_alert_threshold?: number | null
}

export async function fetchAllProjectBudgets(): Promise<ProjectBudget[]> {
  const res = await fetchApi(buildApiUrl('/api/projects/budgets'))
  if (!res.ok) throw new Error('Failed to fetch project budgets')
  return res.json()
}

export async function updateBudgetSettings(
  projectId: string,
  update: BudgetSettingsUpdate,
): Promise<void> {
  const res = await fetchApi(
    buildApiUrl(`/api/projects/${projectId}/permissions`),
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    },
  )
  if (!res.ok)
    throw new Error(`Failed to update budget settings for ${projectId}`)
}
