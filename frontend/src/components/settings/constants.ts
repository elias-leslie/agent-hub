export interface CredentialField {
  credentialType: string
  label: string
  placeholder: string
}

export interface ProviderInfo {
  id: string
  name: string
  hint: string
  oauth?: boolean
  /** Multiple credential fields (e.g., account_id + api_key). When set, overrides the default single API key form. */
  credentialFields?: CredentialField[]
  /** Stored credentials exist but the backend catalog no longer routes here. */
  retired?: boolean
}

/**
 * Display metadata for providers the backend catalog currently routes to.
 * The list of providers itself comes from `/api/models` (`providers`); this
 * table only supplies labels and credential hints for those live ids.
 */
const PROVIDER_METADATA: Record<string, Omit<ProviderInfo, 'id'>> = {
  codex: { name: 'Codex', hint: 'ChatGPT subscription OAuth', oauth: true },
  gemini: { name: 'Gemini', hint: 'Google AI API key' },
  local: { name: 'Local', hint: 'Local OpenAI-compatible endpoint key' },
  xai: { name: 'xAI', hint: 'xAI (Grok) API key' },
  typesafe: { name: 'TypeSafe', hint: 'Typed judgment API credential' },
  nvidia: { name: 'NVIDIA NIM', hint: 'NVIDIA developer API key (nvapi-…)' },
  cloudflare: {
    name: 'Cloudflare',
    hint: 'Workers AI account ID and API token',
    credentialFields: [
      {
        credentialType: 'account_id',
        label: 'Account ID',
        placeholder: 'Enter Cloudflare Account ID',
      },
      {
        credentialType: 'api_key',
        label: 'API Token',
        placeholder: 'Enter Cloudflare API Token',
      },
    ],
  },
}

/**
 * `/api/status` reports health per API adapter family, not per provider.
 * A provider shows the health of the adapter family that serves it.
 */
const PROVIDER_API_FAMILY: Record<string, string> = {
  claude: 'claude-code-cli',
  codex: 'openai-codex-responses',
  gemini: 'google-generative-ai',
  xai: 'openai-completions',
  local: 'openai-completions',
  nvidia: 'openai-completions',
  cloudflare: 'openai-completions',
}

export function getProviderApiFamily(providerId: string): string | undefined {
  return PROVIDER_API_FAMILY[providerId]
}

function titleCaseProviderId(providerId: string): string {
  return providerId
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

/**
 * Resolve display info for a provider card.
 *
 * `displayName` is the backend catalog label for a live provider. Pass
 * `retired: true` for a provider that only appears because stored
 * credentials still reference it; such cards only offer deletion.
 */
export function getProviderInfo(
  providerId: string,
  options: { displayName?: string; retired?: boolean } = {},
): ProviderInfo {
  if (options.retired) {
    return {
      id: providerId,
      name: options.displayName ?? titleCaseProviderId(providerId),
      hint: 'Not in the model catalog. Agent Hub no longer routes to it.',
      retired: true,
    }
  }
  const metadata = PROVIDER_METADATA[providerId]
  if (metadata) {
    return { id: providerId, ...metadata }
  }
  return {
    id: providerId,
    name: options.displayName ?? titleCaseProviderId(providerId),
    hint: 'Provider credential configuration',
  }
}

export function isOAuthProvider(providerId: string): boolean {
  return Boolean(PROVIDER_METADATA[providerId]?.oauth)
}

export function isVisibleSettingsProvider(providerId: string): boolean {
  return (
    providerId !== 'anthropic' &&
    providerId !== 'claude' &&
    providerId !== 'cloudcode' &&
    providerId !== 'antigravity' &&
    !providerId.startsWith('_')
  )
}

export function filterVisibleSettingsProviders(
  providerIds: Iterable<string>,
): string[] {
  return Array.from(new Set(providerIds))
    .filter(isVisibleSettingsProvider)
    .sort((a, b) => a.localeCompare(b))
}

export interface SettingsProviderEntry {
  id: string
  retired: boolean
}

/**
 * Build the Settings provider list from the backend catalog's live provider
 * ids plus any provider ids that still have stored credentials. Credential
 * providers missing from the catalog are retired and offered for deletion.
 */
export function buildSettingsProviders(
  liveProviderIds: Iterable<string>,
  credentialProviderIds: Iterable<string>,
): SettingsProviderEntry[] {
  const live = new Set(liveProviderIds)
  return filterVisibleSettingsProviders([
    ...live,
    ...credentialProviderIds,
  ]).map((id) => ({ id, retired: !live.has(id) }))
}

export interface ProviderColor {
  /** Tailwind background class for the provider dot */
  dot: string
  /** Tailwind border class for provider-tinted cards and chips */
  bg: string
  /** Hex color for charts (recharts strokes and fills, inline bars) */
  chart: string
}

/** One palette for every provider-colored surface, keyed by live provider id. */
export const PROVIDER_COLORS: Record<string, ProviderColor> = {
  claude: { dot: 'bg-amber-400', bg: 'border-amber-500/20', chart: '#f59e0b' },
  cloudflare: {
    dot: 'bg-yellow-400',
    bg: 'border-yellow-500/20',
    chart: '#eab308',
  },
  codex: {
    dot: 'bg-emerald-400',
    bg: 'border-emerald-500/20',
    chart: '#34d399',
  },
  gemini: { dot: 'bg-blue-400', bg: 'border-blue-500/20', chart: '#3b82f6' },
  local: { dot: 'bg-slate-400', bg: 'border-slate-500/20', chart: '#94a3b8' },
  nvidia: { dot: 'bg-lime-400', bg: 'border-lime-500/20', chart: '#84cc16' },
  typesafe: { dot: 'bg-teal-400', bg: 'border-teal-500/20', chart: '#14b8a6' },
  xai: { dot: 'bg-red-400', bg: 'border-red-500/20', chart: '#ef4444' },
}

export const DEFAULT_PROVIDER_COLOR: ProviderColor = {
  dot: 'bg-slate-400',
  bg: 'border-slate-500/20',
  chart: '#94a3b8',
}

export function getProviderColor(providerId: string): ProviderColor {
  return PROVIDER_COLORS[providerId] ?? DEFAULT_PROVIDER_COLOR
}
