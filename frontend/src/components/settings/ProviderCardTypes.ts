import type { Credential, ProviderHealthDetails } from '@/lib/api'
import type { ProviderInfo } from './constants'

/** OAuth status from the /api/oauth/{provider}/status endpoint */
export interface OAuthProviderStatus {
  provider: string
  oauth_status: 'authenticated' | 'expired' | 'not_configured'
  api_key_status: 'configured' | 'not_configured'
  preferred_auth: 'oauth' | 'api_key'
  email?: string | null
}

export type OAuthStatus = OAuthProviderStatus

/** Get normalized OAuth active state */
export function getOAuthActive(
  status: OAuthStatus | undefined,
): 'active' | 'expired' | 'missing' {
  if (!status) return 'missing'
  if (status.oauth_status === 'authenticated') return 'active'
  if (status.oauth_status === 'expired') return 'expired'
  return 'missing'
}

/** Check if any credential (OAuth or API key) is configured */
export function hasAnyAuth(
  status: OAuthStatus | undefined,
  hasApiKey: boolean,
): boolean {
  if (hasApiKey) return true
  if (!status) return false
  return status.oauth_status === 'authenticated'
}

/** Health data from the /api/status endpoint for a single provider */
export interface ProviderHealthData {
  available: boolean
  configured: boolean
  error: string | null
  health: ProviderHealthDetails | null
}

export interface SaveCredentialOptions {
  credentialId?: number
  forceCreate?: boolean
}

export interface ProviderCardProps {
  provider: ProviderInfo
  credentials: Credential[]
  oauthStatus?: OAuthStatus
  healthData?: ProviderHealthData
  colors: { dot: string; bg: string }
  isEditing: boolean
  isAdding: boolean
  isConfirmDelete: boolean
  isSaving: boolean
  error: string | null
  onEdit: () => void
  onAdd: () => void
  onDeleteAll: (ids: number[]) => void
  onSave: (value: string, options?: SaveCredentialOptions) => void
  onSaveMulti?: (fields: Record<string, string>) => void
  onCancel: () => void
  onConfirmDelete: () => void
  onCancelDelete: () => void
  isDeletingThis: boolean
  onOAuthStart?: () => void
  onDisconnectOAuth?: () => void
  isOAuthLoading?: boolean
  isManualPasteActive?: boolean
  onManualExchange?: (input: string) => Promise<void> | void
  onCancelManualPaste?: () => void
  preferredAuth?: 'oauth' | 'api_key'
  onPreferenceChange?: (pref: 'oauth' | 'api_key') => void
  vertexProject?: string
  onVertexProjectChange?: (project: string) => void
  onEditCredential?: (credentialId: number) => void
  onDeleteCredential?: (credentialId: number) => void
  onSetPrimaryCredential?: (credentialId: number) => void
  pendingCredentialDeleteId?: number | null
  onRequestDeleteCredential?: (credentialId: number) => void
  onCancelDeleteCredential?: () => void
}
