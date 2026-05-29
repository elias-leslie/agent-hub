// ─────────────────────────────────────────────────────────────────────────────
// FORMATTERS
// ─────────────────────────────────────────────────────────────────────────────

export function formatCurrency(value: number): string {
  if (value === 0) return '$0.00'
  if (value < 0.01) return `$${value.toFixed(4)}`
  if (value < 1) return `$${value.toFixed(3)}`
  return `$${value.toFixed(2)}`
}

export function formatNumber(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  return value.toLocaleString()
}

export function formatLatency(ms: number | null): string {
  if (ms === null) return '-'
  if (ms < 1) return '<1ms'
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}

export function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`
  return tokens.toString()
}

export function formatModelName(model: string, maxLength: number = 14): string {
  return model
    .replace('claude-', '')
    .replace('gemini-', 'g-')
    .replace('minimax/', '')
    .replace('models/', '')
    .slice(0, maxLength)
}

export function formatRelativeTime(dateStr: string | Date | null): string {
  if (!dateStr) return 'Never'
  const date = typeof dateStr === 'string' ? new Date(dateStr) : dateStr
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffSecs = Math.floor(diffMs / 1000)
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffSecs < 10) return 'just now'
  if (diffSecs < 60) return `${diffSecs}s ago`
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// Relative time tuned for benchmark/run timestamps: coarser buckets and a
// "no runs yet" fallback. Kept distinct from formatRelativeTime above, whose
// finer-grained output is depended on by many other surfaces.
export function formatRelativeAge(iso: string | null | undefined): string {
  if (!iso) {
    return 'No completed runs yet'
  }
  const value = new Date(iso).getTime()
  if (Number.isNaN(value)) {
    return 'Unknown'
  }
  const diffMs = Date.now() - value
  const diffHours = Math.max(Math.round(diffMs / (1000 * 60 * 60)), 0)
  if (diffHours < 1) {
    return 'Less than an hour ago'
  }
  if (diffHours < 24) {
    return `${diffHours}h ago`
  }
  const diffDays = Math.round(diffHours / 24)
  if (diffDays < 30) {
    return `${diffDays}d ago`
  }
  return new Date(iso).toLocaleDateString()
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return 'Pending'
  }
  return `${value.toFixed(1)}%`
}

export function summarizeIssue(
  value: string | null | undefined,
  maxLength: number = 140,
): string {
  if (!value) {
    return 'No issue captured'
  }
  const compact = value.replace(/\s+/g, ' ').trim()
  if (compact.length <= maxLength) {
    return compact
  }
  return `${compact.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`
}
