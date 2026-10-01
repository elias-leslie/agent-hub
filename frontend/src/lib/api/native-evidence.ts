import { fetchApi, getApiBaseUrl } from '../api-config'

export interface NativeEvidenceReceipt {
  source_id: string
  position: number
  source_kind: 'app_server' | 'rollout'
  authenticity: 'collector_attested' | 'local_verified'
  origin: string | null
  disposition: string
}

export interface NativeCommandEvidence {
  entity_id: string
  projection_event_ids: string[]
  status: string
  observed_model: string | null
  receipts: NativeEvidenceReceipt[]
}

export interface NativeEvidenceSummary {
  schema_version: 'native-observation.v1'
  session_id: string
  commands: NativeCommandEvidence[]
  inherited_receipt_count: number
  unresolved_receipt_count: number
  approvals: {
    validated_requests: number
    bound_responses: number
    cleared_requests: number
    unresolved: number
  }
  usage_authority: string
  observed_model: string | null
  next_entity_id: string
  provenance_truncated: boolean
}

export const NATIVE_EVIDENCE_PAGE_SIZE = 100

export function combineNativeEvidencePages(
  pages: NativeEvidenceSummary[],
): NativeEvidenceSummary | undefined {
  const latest = pages.at(-1)
  if (!latest) return undefined
  const commands = new Map<string, NativeCommandEvidence>()
  for (const page of pages)
    for (const command of page.commands)
      commands.set(command.entity_id, command)
  return {
    ...latest,
    commands: [...commands.values()],
    provenance_truncated: pages.some((page) => page.provenance_truncated),
  }
}

export function nativeEvidenceNextCursor(
  lastPage: NativeEvidenceSummary,
): string | undefined {
  return lastPage.commands.length === NATIVE_EVIDENCE_PAGE_SIZE &&
    lastPage.next_entity_id
    ? lastPage.next_entity_id
    : undefined
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}
function count(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}
function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

export function parseNativeEvidenceSummary(
  value: unknown,
): NativeEvidenceSummary {
  if (
    !record(value) ||
    value.schema_version !== 'native-observation.v1' ||
    typeof value.session_id !== 'string' ||
    !Array.isArray(value.commands) ||
    !count(value.inherited_receipt_count) ||
    !count(value.unresolved_receipt_count) ||
    typeof value.usage_authority !== 'string' ||
    !nullableString(value.observed_model) ||
    typeof value.next_entity_id !== 'string' ||
    typeof value.provenance_truncated !== 'boolean' ||
    !record(value.approvals) ||
    ![
      'validated_requests',
      'bound_responses',
      'cleared_requests',
      'unresolved',
    ].every((key) => count((value.approvals as Record<string, unknown>)[key]))
  )
    throw new Error('Native evidence summary is incompatible')
  const commands = value.commands.map((command): NativeCommandEvidence => {
    if (
      !record(command) ||
      typeof command.entity_id !== 'string' ||
      typeof command.status !== 'string' ||
      !Array.isArray(command.projection_event_ids) ||
      !command.projection_event_ids.every((id) => typeof id === 'string') ||
      !nullableString(command.observed_model) ||
      !Array.isArray(command.receipts)
    )
      throw new Error('Native command provenance is incompatible')
    const receipts = command.receipts.map((receipt): NativeEvidenceReceipt => {
      if (
        !record(receipt) ||
        typeof receipt.source_id !== 'string' ||
        !count(receipt.position) ||
        (receipt.source_kind !== 'app_server' &&
          receipt.source_kind !== 'rollout') ||
        (receipt.authenticity !== 'collector_attested' &&
          receipt.authenticity !== 'local_verified') ||
        !nullableString(receipt.origin) ||
        typeof receipt.disposition !== 'string'
      )
        throw new Error('Native receipt provenance is incompatible')
      return {
        source_id: receipt.source_id,
        position: receipt.position,
        source_kind: receipt.source_kind,
        authenticity: receipt.authenticity,
        origin: receipt.origin,
        disposition: receipt.disposition,
      }
    })
    return {
      entity_id: command.entity_id,
      projection_event_ids: command.projection_event_ids as string[],
      status: command.status,
      observed_model: command.observed_model,
      receipts,
    }
  })
  return {
    schema_version: 'native-observation.v1',
    session_id: value.session_id,
    commands,
    inherited_receipt_count: value.inherited_receipt_count,
    unresolved_receipt_count: value.unresolved_receipt_count,
    approvals: {
      validated_requests: value.approvals.validated_requests as number,
      bound_responses: value.approvals.bound_responses as number,
      cleared_requests: value.approvals.cleared_requests as number,
      unresolved: value.approvals.unresolved as number,
    },
    usage_authority: value.usage_authority,
    observed_model: value.observed_model,
    next_entity_id: value.next_entity_id,
    provenance_truncated: value.provenance_truncated,
  }
}

export async function fetchNativeEvidenceSummary(
  sessionId: string,
  afterEntityId = '',
): Promise<NativeEvidenceSummary> {
  const query = new URLSearchParams({
    limit: String(NATIVE_EVIDENCE_PAGE_SIZE),
    after_entity_id: afterEntityId,
  })
  const response = await fetchApi(
    `${getApiBaseUrl()}/api/session-ingestion/sessions/${encodeURIComponent(sessionId)}/native-evidence-summary?${query}`,
  )
  if (!response.ok)
    throw new Error(`Native evidence summary unavailable: ${response.status}`)
  const value: unknown = await response.json()
  const summary = parseNativeEvidenceSummary(value)
  if (summary.session_id !== sessionId)
    throw new Error('Native evidence session mismatch')
  return summary
}
