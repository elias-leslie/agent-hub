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
}

const PROVIDER_METADATA: Record<string, Omit<ProviderInfo, 'id'>> = {
  claude: { name: 'Claude', hint: 'Anthropic — OAuth or API key', oauth: true },
  codex: { name: 'Codex', hint: 'ChatGPT subscription OAuth', oauth: true },
  deepseek: { name: 'DeepSeek', hint: 'DeepSeek API key' },
  gemini: { name: 'Gemini', hint: 'Google AI API key' },
  'kimi-code': { name: 'Kimi Code', hint: 'Kimi Code subscription key' },
  local: { name: 'Local', hint: 'Local OpenAI-compatible endpoint key' },
  moonshot: { name: 'Moonshot', hint: 'Moonshot/Kimi API key' },
  openai: { name: 'OpenAI', hint: 'OpenAI platform API key' },
  openrouter: { name: 'OpenRouter', hint: 'OpenRouter API key' },
  xai: { name: 'xAI', hint: 'xAI (Grok) API key' },
  zhipu: { name: 'Zhipu', hint: 'Zhipu AI (GLM) API key' },
  minimax: { name: 'MiniMax', hint: 'MiniMax API key' },
  nvidia: { name: 'NVIDIA NIM', hint: 'NVIDIA developer API key (nvapi-…)' },
  cloudflare: {
    name: 'Cloudflare',
    hint: 'Workers AI — Account ID + API Token',
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

function titleCaseProviderId(providerId: string): string {
  return providerId
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function getProviderInfo(providerId: string): ProviderInfo {
  const metadata = PROVIDER_METADATA[providerId]
  if (metadata) {
    return { id: providerId, ...metadata }
  }
  return {
    id: providerId,
    name: titleCaseProviderId(providerId),
    hint: 'Provider credential configuration',
  }
}

export function listKnownProviderIds(): string[] {
  return filterVisibleSettingsProviders(Object.keys(PROVIDER_METADATA))
}

export function isOAuthProvider(providerId: string): boolean {
  return Boolean(PROVIDER_METADATA[providerId]?.oauth)
}

export function isVisibleSettingsProvider(providerId: string): boolean {
  return (
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

export const PROVIDER_COLORS: Record<string, { dot: string; bg: string }> = {
  claude: { dot: 'bg-amber-400', bg: 'border-amber-500/20' },
  codex: { dot: 'bg-emerald-400', bg: 'border-emerald-500/20' },
  deepseek: { dot: 'bg-cyan-400', bg: 'border-cyan-500/20' },
  gemini: { dot: 'bg-blue-400', bg: 'border-blue-500/20' },
  'kimi-code': { dot: 'bg-pink-400', bg: 'border-pink-500/20' },
  local: { dot: 'bg-slate-400', bg: 'border-slate-500/20' },
  moonshot: { dot: 'bg-violet-400', bg: 'border-violet-500/20' },
  openai: { dot: 'bg-green-400', bg: 'border-green-500/20' },
  openrouter: { dot: 'bg-purple-400', bg: 'border-purple-500/20' },
  xai: { dot: 'bg-red-400', bg: 'border-red-500/20' },
  zhipu: { dot: 'bg-teal-400', bg: 'border-teal-500/20' },
  minimax: { dot: 'bg-orange-400', bg: 'border-orange-500/20' },
  nvidia: { dot: 'bg-lime-400', bg: 'border-lime-500/20' },
  cloudflare: { dot: 'bg-yellow-400', bg: 'border-yellow-500/20' },
}
