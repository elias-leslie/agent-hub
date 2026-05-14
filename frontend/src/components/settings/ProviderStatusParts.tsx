'use client'

import { Activity, AlertTriangle, Clock, Key, Shield, Zap } from 'lucide-react'
import type { Credential } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { ProviderInfo } from './constants'
import type {
  OAuthProviderStatus,
  ProviderHealthData,
} from './ProviderCardTypes'
import { formatLatency, timeAgo, unixTimeAgo } from './ProviderCardUtils'

// ---------------------------------------------------------------------------
// Auth Badges
// ---------------------------------------------------------------------------

export function AuthBadges({
  isOAuth,
  hasApiKey,
  isConfigured,
  primaryCredential,
  providerStatus,
  provider,
  credentials,
}: {
  isOAuth: boolean
  hasApiKey: boolean
  isConfigured: boolean
  primaryCredential?: Credential
  providerStatus: OAuthProviderStatus | null
  provider: ProviderInfo
  credentials: Credential[]
}) {
  const badges: React.ReactNode[] = []

  if (isOAuth) {
    const oauthState = providerStatus?.oauth_status
    const isAuth = oauthState === 'authenticated'
    const isExpired = oauthState === 'expired'
    badges.push(
      <span
        key="oauth"
        className={cn(
          'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium',
          isAuth
            ? 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/20'
            : isExpired
              ? 'bg-red-500/15 text-red-400 ring-1 ring-red-500/20'
              : 'bg-slate-500/15 text-slate-400 ring-1 ring-slate-500/20',
        )}
      >
        <Shield className="h-2.5 w-2.5" />
        OAuth {isAuth ? 'Active' : isExpired ? 'Expired' : '—'}
      </span>,
    )
    if (isAuth && providerStatus?.email) {
      badges.push(
        <span key="email" className="text-[10px] text-slate-500">
          {providerStatus.email}
        </span>,
      )
    }
  }

  // API key badge(s)
  if (hasApiKey && isConfigured && primaryCredential) {
    // Check if we have multiple credentials of type "api_key" (for single-field providers like Gemini)
    const apiKeyCount = provider.credentialFields
      ? 1
      : credentials.filter(
          (c) => c.credential_type === 'api_key' || !c.credential_type,
        ).length

    badges.push(
      <span
        key="apikey"
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-500/15 text-amber-400 ring-1 ring-blue-500/20"
      >
        <Key className="h-2.5 w-2.5" />
        {apiKeyCount > 1 ? `API Key (${apiKeyCount})` : 'API Key'}
      </span>,
    )
  }

  if (badges.length === 0) return null

  return <div className="flex items-center gap-1.5 flex-wrap">{badges}</div>
}

// ---------------------------------------------------------------------------
// Health Metrics Strip
// ---------------------------------------------------------------------------

export function HealthMetricsStrip({
  health,
}: {
  health: NonNullable<ProviderHealthData['health']>
}) {
  const isLatencyOnlySlow =
    health.state === 'degraded' &&
    health.availability >= 1 &&
    health.consecutive_failures === 0 &&
    !health.last_error

  const stateColors: Record<string, string> = {
    healthy: 'text-emerald-400',
    degraded: 'text-amber-400',
    unavailable: 'text-red-400',
    unknown: 'text-slate-400',
  }

  const stateLabels: Record<string, string> = {
    healthy: 'Healthy',
    degraded: 'Degraded',
    unavailable: 'Down',
    unknown: 'Unknown',
  }

  const stateBg: Record<string, string> = {
    healthy: 'bg-emerald-500/8',
    degraded: 'bg-amber-500/8',
    unavailable: 'bg-red-500/8',
    unknown: 'bg-slate-500/8',
  }

  const availPct = Math.round(health.availability * 100)

  return (
    <div
      className={cn(
        'flex items-center gap-3 px-2 py-1 rounded-md text-[10px]',
        stateBg[health.state] ?? 'bg-slate-500/8',
      )}
    >
      {/* State indicator */}
      <span
        className={cn(
          'font-semibold uppercase tracking-wider',
          stateColors[health.state],
        )}
      >
        <Activity className="h-2.5 w-2.5 inline mr-0.5 -mt-px" />
        {isLatencyOnlySlow
          ? 'Slow'
          : (stateLabels[health.state] ?? health.state)}
      </span>

      <span className="text-slate-600">|</span>

      {/* Latency */}
      <span className="text-slate-400">
        <Zap className="h-2.5 w-2.5 inline mr-0.5 -mt-px" />
        {formatLatency(health.latency_ms)}
      </span>

      <span className="text-slate-600">|</span>

      {/* Availability */}
      <span
        className={cn(
          availPct >= 95
            ? 'text-emerald-400'
            : availPct >= 70
              ? 'text-amber-400'
              : 'text-red-400',
        )}
      >
        {availPct}% avail
      </span>

      {/* Error info */}
      {health.consecutive_failures > 0 && (
        <>
          <span className="text-slate-600">|</span>
          <span className="text-red-400">
            <AlertTriangle className="h-2.5 w-2.5 inline mr-0.5 -mt-px" />
            {health.consecutive_failures} fail
            {health.consecutive_failures > 1 ? 's' : ''}
          </span>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Timestamp Row
// ---------------------------------------------------------------------------

export function TimestampRow({
  authSince,
  healthData,
}: {
  authSince: string | null
  healthData?: ProviderHealthData
}) {
  const lastCheck = healthData?.health?.last_check
  const lastSuccess = healthData?.health?.last_success

  // No timestamps to show
  if (!authSince && !lastCheck) return null

  return (
    <div className="flex items-center gap-3 text-[10px] text-slate-500">
      {authSince && (
        <span className="flex items-center gap-0.5">
          <Clock className="h-2.5 w-2.5" />
          Credentials updated {timeAgo(authSince)}
        </span>
      )}
      {lastCheck && lastCheck > 0 && (
        <span>Checked {unixTimeAgo(lastCheck)}</span>
      )}
      {lastSuccess && lastSuccess > 0 && lastSuccess !== lastCheck && (
        <span className="text-emerald-500/70">
          Last OK {unixTimeAgo(lastSuccess)}
        </span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Preference Toggle
// ---------------------------------------------------------------------------

export function PreferenceToggle({
  preferredAuth,
  onPreferenceChange,
}: {
  preferredAuth: 'oauth' | 'api_key'
  onPreferenceChange: (pref: 'oauth' | 'api_key') => void
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] text-slate-500">Prefer:</span>
      <div className="flex rounded-md border border-slate-700 overflow-hidden">
        <button
          onClick={() => onPreferenceChange('oauth')}
          className={cn(
            'px-2 py-0.5 text-[10px] font-medium transition-colors',
            preferredAuth === 'oauth'
              ? 'bg-emerald-600 text-white'
              : 'bg-slate-800 text-slate-500 hover:bg-slate-700',
          )}
        >
          OAuth
        </button>
        <button
          onClick={() => onPreferenceChange('api_key')}
          className={cn(
            'px-2 py-0.5 text-[10px] font-medium transition-colors',
            preferredAuth === 'api_key'
              ? 'bg-amber-500 text-slate-950'
              : 'bg-slate-800 text-slate-500 hover:bg-slate-700',
          )}
        >
          API Key
        </button>
      </div>
    </div>
  )
}
