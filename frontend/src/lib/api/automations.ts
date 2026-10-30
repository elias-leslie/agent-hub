import { buildApiUrl, fetchApi } from '../api-config'

export type ScheduleType = 'at' | 'every' | 'cron'
export type ConfigValue =
  | string
  | number
  | boolean
  | null
  | ConfigValue[]
  | { [key: string]: ConfigValue }
export type Config = Record<string, ConfigValue>

export type ConfigFieldType =
  | 'string'
  | 'integer'
  | 'number'
  | 'boolean'
  | 'array'
  | 'object'
  | 'null'

export interface ConfigField {
  type?: ConfigFieldType | ConfigFieldType[]
  anyOf?: ConfigField[]
  title?: string
  description?: string
  enum?: Array<string | number>
  minimum?: number
  maximum?: number
  default?: ConfigValue
  items?: ConfigField
}

export interface ConfigSchema {
  properties?: Record<string, ConfigField>
  required?: string[]
}

export interface AutomationDefinition {
  workflow_key: string
  version: number
  label: string
  description?: string | null
  owner_project_id: string
  dispatch_kind: string
  default_schedule: { type?: ScheduleType; value?: string; timezone?: string }
  default_enabled: boolean
  config_schema?: ConfigSchema | null
  policy_schema?: ConfigSchema | null
  owner_contract?: string | null
  manual_when_disabled?: boolean
  manual_advances_cursor?: boolean
  overlap_strategy?: string
}

export interface AutomationRegistry {
  definitions: AutomationDefinition[]
}

export interface AutomationReviewState {
  unreviewed_count: number
  last_reviewed_at: string | null
}

export interface AutomationProfile {
  id: string
  project_id: string
  subject_id: string | null
  workflow_key: string
  definition_version: number
  label: string
  schedule_type: ScheduleType
  schedule_value: string
  schedule_timezone: string
  config: Config
  enabled: boolean
  effective_enabled: boolean
  gate_reasons: string[]
  clock_owner: 'legacy' | 'central'
  next_run_at: string | null
  last_run_at: string | null
  unreviewed_count: number
  last_reviewed_at: string | null
  revision: number
}

export interface AutomationProfilesPage {
  items: AutomationProfile[]
  total: number
}

export interface AutomationPolicy {
  project_id: string
  enabled: boolean
  config: Config
  revision: number
  sync_revision: number
  sync_pending: boolean
  updated_at: string | null
}

export interface AutomationRun {
  id: string
  profile_id: string
  project_id: string
  workflow_key: string
  definition_version: number
  profile_revision: number
  occurrence_key: string
  scheduled_for: string | null
  status: string
  trigger?: string | null
  gate_reasons: string[]
  created_at: string
  accepted_at?: string | null
  completed_at?: string | null
  error?: string | null
  owner_run_id?: string | null
  owner_receipt?: Config | null
}

export interface AutomationRunsPage {
  items: AutomationRun[]
  total: number
}

export interface AutomationProfileInput {
  project_id: string
  subject_id: string | null
  workflow_key: string
  label: string
  schedule_type: ScheduleType
  schedule_value: string
  schedule_timezone: string
  config: Config
  enabled: boolean
}

async function readResponse<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const rawDetail =
      body && typeof body === 'object' && 'detail' in body ? body.detail : null
    const detail =
      typeof rawDetail === 'string'
        ? rawDetail
        : rawDetail == null
          ? `${response.status} ${response.statusText}`
          : JSON.stringify(rawDetail)
    throw new Error(`${action}: ${detail}`)
  }
  return response.json() as Promise<T>
}

const endpoint = (path: string) => buildApiUrl(`/api/automations${path}`)

export async function fetchAutomationRegistry(): Promise<AutomationRegistry> {
  return readResponse<AutomationRegistry>(
    await fetchApi(endpoint('/registry')),
    'Failed to load automation catalog',
  )
}

export async function fetchAutomationProfiles(
  projectId?: string,
  limit = 200,
  offset = 0,
): Promise<AutomationProfilesPage> {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  if (projectId) query.set('project_id', projectId)
  return readResponse<AutomationProfilesPage>(
    await fetchApi(endpoint(`/profiles?${query}`)),
    'Failed to load automation profiles',
  )
}

export async function createAutomationProfile(
  payload: AutomationProfileInput,
): Promise<AutomationProfile> {
  return readResponse<AutomationProfile>(
    await fetchApi(endpoint('/profiles'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
    'Failed to create automation',
  )
}

export async function updateAutomationProfile(
  id: string,
  payload: Partial<
    Omit<AutomationProfileInput, 'project_id' | 'workflow_key'>
  > & { expected_revision: number },
): Promise<AutomationProfile> {
  return readResponse<AutomationProfile>(
    await fetchApi(endpoint(`/profiles/${encodeURIComponent(id)}`), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
    'Failed to save automation',
  )
}

export async function fetchAutomationPolicy(
  projectId: string,
): Promise<AutomationPolicy> {
  return readResponse<AutomationPolicy>(
    await fetchApi(
      endpoint(`/projects/${encodeURIComponent(projectId)}/policy`),
    ),
    'Failed to load project policy',
  )
}

export async function updateAutomationPolicy(
  projectId: string,
  payload: Pick<AutomationPolicy, 'enabled' | 'config'> & {
    expected_revision: number
  },
): Promise<AutomationPolicy> {
  return readResponse<AutomationPolicy>(
    await fetchApi(
      endpoint(`/projects/${encodeURIComponent(projectId)}/policy`),
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),
    'Failed to save project policy',
  )
}

export async function runAutomationProfile(id: string): Promise<AutomationRun> {
  return readResponse<AutomationRun>(
    await fetchApi(endpoint(`/profiles/${encodeURIComponent(id)}/run`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    }),
    'Failed to start automation',
  )
}

export async function reviewAutomationProfile(
  id: string,
): Promise<AutomationProfile> {
  return readResponse<AutomationProfile>(
    await fetchApi(endpoint(`/profiles/${encodeURIComponent(id)}/review`), {
      method: 'POST',
    }),
    'Failed to mark runs reviewed',
  )
}

export async function fetchAutomationRuns(
  filters: {
    profileId?: string
    projectId?: string
    status?: string
    limit?: number
    offset?: number
  } = {},
): Promise<AutomationRunsPage> {
  const query = new URLSearchParams({
    limit: String(filters.limit ?? 30),
    offset: String(filters.offset ?? 0),
  })
  if (filters.profileId) query.set('profile_id', filters.profileId)
  if (filters.projectId) query.set('project_id', filters.projectId)
  if (filters.status) query.set('status', filters.status)
  return readResponse<AutomationRunsPage>(
    await fetchApi(endpoint(`/runs?${query}`)),
    'Failed to load automation runs',
  )
}
