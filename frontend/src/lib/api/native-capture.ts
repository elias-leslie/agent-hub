import { fetchApi, getApiBaseUrl } from '../api-config'

export interface NativeCaptureSource {
  source_id: string
  kind: string
  provider_version: string
  schema_fingerprint: string
  authenticity: string
  committed_position: number
  receipt_count: number
  max_position: number
  first_missing_position: number | null
  issues: Record<string, number>
  protocol_supported?: boolean
  generation?: number
  projection_mode?: string
  freshness?: string
  last_received_at?: string | null
  dispositions?: Record<string, number>
  capture_health: { state: string; capture_gaps?: number } | null
}

export interface NativeCaptureStatus {
  schema_version: 'native-observation.v1'
  session_id: string
  capture_mode: string
  projection_authority: string
  promotion_state: string
  observed_model: string | null
  promotion_requested?: boolean
  promotion_eligible?: boolean
  promotion_blockers?: string[]
  delivery_status?: string
  sources: NativeCaptureSource[]
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function count(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

// The health endpoint is a content-free DTO. Reject incompatible responses and
// deliberately select fields so raw evidence can never enter this view.
export function parseNativeCaptureStatus(value: unknown): NativeCaptureStatus {
  if (
    !record(value) ||
    value.schema_version !== 'native-observation.v1' ||
    typeof value.session_id !== 'string' ||
    !Array.isArray(value.sources) ||
    typeof value.capture_mode !== 'string' ||
    typeof value.projection_authority !== 'string' ||
    typeof value.promotion_state !== 'string' ||
    (value.observed_model !== null && typeof value.observed_model !== 'string')
  ) {
    throw new Error('Native capture status is incompatible')
  }
  const sources = value.sources.map((source): NativeCaptureSource => {
    if (
      !record(source) ||
      ![
        'source_id',
        'kind',
        'provider_version',
        'schema_fingerprint',
        'authenticity',
      ].every((key) => typeof source[key] === 'string') ||
      !['committed_position', 'receipt_count', 'max_position'].every((key) =>
        count(source[key]),
      ) ||
      (source.first_missing_position !== null &&
        !count(source.first_missing_position)) ||
      !record(source.issues) ||
      !Object.values(source.issues).every(count) ||
      (source.capture_health !== null &&
        (!record(source.capture_health) ||
          typeof source.capture_health.state !== 'string'))
    ) {
      throw new Error('Native capture source is incompatible')
    }
    const health = record(source.capture_health) ? source.capture_health : null
    return {
      source_id: source.source_id as string,
      kind: source.kind as string,
      provider_version: source.provider_version as string,
      schema_fingerprint: source.schema_fingerprint as string,
      authenticity: source.authenticity as string,
      committed_position: source.committed_position as number,
      receipt_count: source.receipt_count as number,
      max_position: source.max_position as number,
      first_missing_position: source.first_missing_position as number | null,
      issues: source.issues as Record<string, number>,
      ...(typeof source.protocol_supported === 'boolean'
        ? { protocol_supported: source.protocol_supported }
        : {}),
      ...(count(source.generation) ? { generation: source.generation } : {}),
      ...(typeof source.projection_mode === 'string'
        ? { projection_mode: source.projection_mode }
        : {}),
      ...(typeof source.freshness === 'string'
        ? { freshness: source.freshness }
        : {}),
      ...(source.last_received_at === null ||
      typeof source.last_received_at === 'string'
        ? { last_received_at: source.last_received_at }
        : {}),
      ...(record(source.dispositions) &&
      Object.values(source.dispositions).every(count)
        ? { dispositions: source.dispositions as Record<string, number> }
        : {}),
      capture_health: health
        ? {
            state: health.state as string,
            ...(count(health.capture_gaps)
              ? { capture_gaps: health.capture_gaps }
              : {}),
          }
        : null,
    }
  })
  return {
    schema_version: 'native-observation.v1',
    session_id: value.session_id,
    capture_mode: value.capture_mode,
    projection_authority: value.projection_authority,
    promotion_state: value.promotion_state,
    observed_model: value.observed_model,
    ...(typeof value.promotion_requested === 'boolean'
      ? { promotion_requested: value.promotion_requested }
      : {}),
    ...(typeof value.promotion_eligible === 'boolean'
      ? { promotion_eligible: value.promotion_eligible }
      : {}),
    ...(Array.isArray(value.promotion_blockers) &&
    value.promotion_blockers.every((blocker) => typeof blocker === 'string')
      ? { promotion_blockers: value.promotion_blockers as string[] }
      : {}),
    ...(typeof value.delivery_status === 'string'
      ? { delivery_status: value.delivery_status }
      : {}),
    sources,
  }
}

export async function fetchNativeCaptureStatus(
  sessionId: string,
): Promise<NativeCaptureStatus> {
  const response = await fetchApi(
    `${getApiBaseUrl()}/api/session-ingestion/sessions/${encodeURIComponent(sessionId)}/native-capture`,
  )
  if (!response.ok)
    throw new Error(`Native capture status unavailable: ${response.status}`)
  const value: unknown = await response.json()
  const status = parseNativeCaptureStatus(value)
  if (status.session_id !== sessionId)
    throw new Error('Native capture session mismatch')
  return status
}
