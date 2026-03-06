"use client";

import {
  Shield,
  Key,
  Activity,
  Clock,
  Zap,
  AlertTriangle,
  ArrowUp,
  Pencil,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Credential } from "@/lib/api";
import type { ProviderInfo } from "./constants";
import {
  type OAuthStatus,
  type OAuthProviderStatus,
  type ClaudeOAuthStatus,
  type ProviderHealthData,
  isClaudeStatus,
} from "./ProviderCardTypes";
import { VertexProjectInput } from "./VertexProjectInput";
import { timeAgo, unixTimeAgo, formatDuration, formatLatency } from "./ProviderCardUtils";

interface ProviderStatusDisplayProps {
  provider: ProviderInfo;
  credentials: Credential[];
  oauthStatus?: OAuthStatus;
  healthData?: ProviderHealthData;
  isConfigured: boolean;
  isOAuth: boolean;
  isClaude: boolean;
  hasOAuthToken: boolean;
  hasApiKey: boolean;
  hasBothCredentials: boolean;
  preferredAuth: "oauth" | "api_key";
  providerStatus: OAuthProviderStatus | null;
  onPreferenceChange?: (pref: "oauth" | "api_key") => void;
  vertexProject?: string;
  onVertexProjectChange?: (project: string) => void;
  onEditCredential?: (credentialId: number) => void;
  onDeleteCredential?: (credentialId: number) => void;
  onSetPrimaryCredential?: (credentialId: number) => void;
}

export function ProviderStatusDisplay({
  provider,
  credentials,
  oauthStatus,
  healthData,
  isConfigured,
  isOAuth,
  isClaude,
  hasOAuthToken,
  hasApiKey,
  hasBothCredentials,
  preferredAuth,
  providerStatus,
  onPreferenceChange,
  vertexProject,
  onVertexProjectChange,
  onEditCredential,
  onDeleteCredential,
  onSetPrimaryCredential,
}: ProviderStatusDisplayProps) {
  // Primary credential for single-field providers
  const primaryCredential = credentials.find((c) => c.credential_type === "api_key") ?? credentials[0];

  // Latest credential updated_at = "last authenticated"
  const authSince = credentials.length > 0
    ? credentials.reduce((latest, c) =>
      new Date(c.updated_at) > new Date(latest.updated_at) ? c : latest
    ).updated_at
    : null;

  // Not configured at all — show hint
  const noAuth = !isConfigured && (!isOAuth || !oauthStatus || (
    isClaudeStatus(oauthStatus) ? oauthStatus.status === "missing" : oauthStatus.oauth_status === "not_configured"
  ));

  if (noAuth && !healthData?.configured) {
    return (
      <p className="text-xs text-slate-500 mt-0.5">
        Not configured · {provider.hint}
      </p>
    );
  }

  return (
    <div className="mt-1 space-y-1.5">
      {/* Row 1: Auth method badges */}
      <AuthBadges
        isOAuth={isOAuth}
        isClaude={isClaude}
        oauthStatus={oauthStatus}
        hasOAuthToken={hasOAuthToken}
        hasApiKey={hasApiKey}
        isConfigured={isConfigured}
        primaryCredential={primaryCredential}
        providerStatus={providerStatus}
        hasBothCredentials={hasBothCredentials}
        preferredAuth={preferredAuth}
        onPreferenceChange={onPreferenceChange}
        provider={provider}
        credentials={credentials}
      />

      {/* Row 2: Health metrics strip (when health data available) */}
      {healthData?.health && healthData.configured && (
        <HealthMetricsStrip health={healthData.health} />
      )}

      {/* Row 3: Timestamps — authenticated since + last checked */}
      <TimestampRow
        authSince={authSince}
        healthData={healthData}
        isClaude={isClaude}
        oauthStatus={oauthStatus}
      />

      {/* Multi-field credential display */}
      {isConfigured && provider.credentialFields && credentials.length > 0 && (
        <div className="space-y-0.5">
          {credentials.map((cred) => {
            const fieldDef = provider.credentialFields?.find(
              (f) => f.credentialType === cred.credential_type,
            );
            return (
              <p key={cred.id} className="text-[10px] text-slate-500 truncate font-mono">
                {fieldDef?.label ?? cred.credential_type}: {cred.value_masked}
              </p>
            );
          })}
        </div>
      )}

      {/* Single-field credential display (supports multiple API keys) */}
      {isConfigured && !provider.credentialFields && credentials.length > 0 && (
        <div className="space-y-0.5">
          {credentials.map((cred, idx) => (
            <div key={cred.id} className="flex items-center gap-1.5 text-[10px] text-slate-500 truncate">
              {credentials.length > 1 && (
                <span className="font-medium text-slate-400">
                  {idx === 0 ? "Primary:" : `Key ${idx + 1}:`}
                </span>
              )}
              <code className="font-mono bg-slate-100 dark:bg-slate-800 px-1 rounded">
                {cred.value_masked}
              </code>
              {(onEditCredential || onDeleteCredential) && (
                <div className="inline-flex items-center gap-0.5 ml-0.5">
                  {onEditCredential && (
                    <button
                      onClick={() => onEditCredential(cred.id)}
                      className="p-0.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors"
                      title="Update this key"
                    >
                      <Pencil className="h-2.5 w-2.5" />
                    </button>
                  )}
                  {onDeleteCredential && (
                    <button
                      onClick={() => onDeleteCredential(cred.id)}
                      className="p-0.5 rounded hover:bg-red-50 dark:hover:bg-red-950/30 text-slate-500 dark:text-slate-400 hover:text-red-500 transition-colors"
                      title="Delete this key"
                    >
                      <Trash2 className="h-2.5 w-2.5" />
                    </button>
                  )}
                  {onSetPrimaryCredential && idx > 0 && (
                    <button
                      onClick={() => onSetPrimaryCredential(cred.id)}
                      className="p-0.5 rounded hover:bg-blue-50 dark:hover:bg-blue-950/30 text-slate-500 dark:text-slate-400 hover:text-blue-500 transition-colors"
                      title="Make primary"
                    >
                      <ArrowUp className="h-2.5 w-2.5" />
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Preference toggle for dual-auth providers */}
      {hasBothCredentials && provider.supportsApiKey && onPreferenceChange && (
        <PreferenceToggle preferredAuth={preferredAuth} onPreferenceChange={onPreferenceChange} />
      )}

      {/* Vertex project input */}
      {onVertexProjectChange && (
        <VertexProjectInput
          value={vertexProject ?? ""}
          onSave={onVertexProjectChange}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Auth Badges
// ---------------------------------------------------------------------------

function AuthBadges({
  isOAuth,
  isClaude,
  oauthStatus,
  hasOAuthToken,
  hasApiKey,
  isConfigured,
  primaryCredential,
  providerStatus,
  hasBothCredentials,
  preferredAuth,
  onPreferenceChange,
  provider,
  credentials,
}: {
  isOAuth: boolean;
  isClaude: boolean;
  oauthStatus?: OAuthStatus;
  hasOAuthToken: boolean;
  hasApiKey: boolean;
  isConfigured: boolean;
  primaryCredential?: Credential;
  providerStatus: OAuthProviderStatus | null;
  hasBothCredentials: boolean;
  preferredAuth: "oauth" | "api_key";
  onPreferenceChange?: (pref: "oauth" | "api_key") => void;
  provider: ProviderInfo;
  credentials: Credential[];
}) {
  const badges: React.ReactNode[] = [];

  if (isOAuth) {
    if (isClaude && oauthStatus && isClaudeStatus(oauthStatus)) {
      const isValid = oauthStatus.status === "valid";
      const isExpired = oauthStatus.status === "expired";
      badges.push(
        <span
          key="oauth"
          className={cn(
            "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium",
            isValid
              ? "bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/20"
              : isExpired
                ? "bg-red-500/15 text-red-400 ring-1 ring-red-500/20"
                : "bg-slate-500/15 text-slate-400 ring-1 ring-slate-500/20",
          )}
        >
          <Shield className="h-2.5 w-2.5" />
          OAuth {isValid ? "Active" : isExpired ? "Expired" : "—"}
        </span>,
      );
      if (isValid && oauthStatus.expires_in_seconds != null) {
        badges.push(
          <span key="expires" className="text-[10px] text-slate-500">
            expires in {formatDuration(oauthStatus.expires_in_seconds)}
          </span>,
        );
      }
      if (isExpired) {
        badges.push(
          <span key="reauth" className="text-[10px] text-red-400">
            run `claude` to re-auth
          </span>,
        );
      }
    } else {
      // Non-Claude OAuth providers
      const oauthState = providerStatus?.oauth_status;
      const isAuth = oauthState === "authenticated";
      const isExpired = oauthState === "expired";
      badges.push(
        <span
          key="oauth"
          className={cn(
            "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium",
            isAuth
              ? "bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/20"
              : isExpired
                ? "bg-red-500/15 text-red-400 ring-1 ring-red-500/20"
                : "bg-slate-500/15 text-slate-400 ring-1 ring-slate-500/20",
          )}
        >
          <Shield className="h-2.5 w-2.5" />
          OAuth {isAuth ? "Active" : isExpired ? "Expired" : "—"}
        </span>,
      );
      if (isAuth && providerStatus?.email) {
        badges.push(
          <span key="email" className="text-[10px] text-slate-500">{providerStatus.email}</span>,
        );
      }
    }
  }

  // API key badge(s)
  if (hasApiKey && isConfigured && primaryCredential) {
    // Check if we have multiple credentials of type "api_key" (for single-field providers like Gemini)
    const apiKeyCount = provider.credentialFields ? 1 : credentials.filter(c => c.credential_type === "api_key" || !c.credential_type).length;

    badges.push(
      <span
        key="apikey"
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-500/15 text-blue-400 ring-1 ring-blue-500/20"
      >
        <Key className="h-2.5 w-2.5" />
        {apiKeyCount > 1 ? `API Key (${apiKeyCount})` : "API Key"}
      </span>,
    );
  }

  if (badges.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {badges}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Health Metrics Strip
// ---------------------------------------------------------------------------

function HealthMetricsStrip({ health }: { health: NonNullable<ProviderHealthData["health"]> }) {
  const stateColors: Record<string, string> = {
    healthy: "text-emerald-400",
    degraded: "text-amber-400",
    unavailable: "text-red-400",
    unknown: "text-slate-400",
  };

  const stateLabels: Record<string, string> = {
    healthy: "Healthy",
    degraded: "Degraded",
    unavailable: "Down",
    unknown: "Unknown",
  };

  const stateBg: Record<string, string> = {
    healthy: "bg-emerald-500/8",
    degraded: "bg-amber-500/8",
    unavailable: "bg-red-500/8",
    unknown: "bg-slate-500/8",
  };

  const availPct = Math.round(health.availability * 100);

  return (
    <div className={cn(
      "flex items-center gap-3 px-2 py-1 rounded-md text-[10px]",
      stateBg[health.state] ?? "bg-slate-500/8",
    )}>
      {/* State indicator */}
      <span className={cn("font-semibold uppercase tracking-wider", stateColors[health.state])}>
        <Activity className="h-2.5 w-2.5 inline mr-0.5 -mt-px" />
        {stateLabels[health.state] ?? health.state}
      </span>

      <span className="text-slate-600">|</span>

      {/* Latency */}
      <span className="text-slate-400">
        <Zap className="h-2.5 w-2.5 inline mr-0.5 -mt-px" />
        {formatLatency(health.latency_ms)}
      </span>

      <span className="text-slate-600">|</span>

      {/* Availability */}
      <span className={cn(
        availPct >= 95 ? "text-emerald-400" : availPct >= 70 ? "text-amber-400" : "text-red-400",
      )}>
        {availPct}% avail
      </span>

      {/* Error info */}
      {health.consecutive_failures > 0 && (
        <>
          <span className="text-slate-600">|</span>
          <span className="text-red-400">
            <AlertTriangle className="h-2.5 w-2.5 inline mr-0.5 -mt-px" />
            {health.consecutive_failures} fail{health.consecutive_failures > 1 ? "s" : ""}
          </span>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Timestamp Row
// ---------------------------------------------------------------------------

function TimestampRow({
  authSince,
  healthData,
  isClaude,
  oauthStatus,
}: {
  authSince: string | null;
  healthData?: ProviderHealthData;
  isClaude: boolean;
  oauthStatus?: OAuthStatus;
}) {
  const lastCheck = healthData?.health?.last_check;
  const lastSuccess = healthData?.health?.last_success;

  // No timestamps to show
  if (!authSince && !lastCheck) return null;

  return (
    <div className="flex items-center gap-3 text-[10px] text-slate-500">
      {authSince && (
        <span className="flex items-center gap-0.5">
          <Clock className="h-2.5 w-2.5" />
          Authenticated {timeAgo(authSince)}
        </span>
      )}
      {/* For Claude with valid OAuth but no DB credential, show token expiry instead */}
      {!authSince && isClaude && oauthStatus && isClaudeStatus(oauthStatus) && oauthStatus.status === "valid" && (
        <span className="flex items-center gap-0.5">
          <Shield className="h-2.5 w-2.5" />
          OAuth active via CLI
        </span>
      )}
      {lastCheck && lastCheck > 0 && (
        <span>
          Checked {unixTimeAgo(lastCheck)}
        </span>
      )}
      {lastSuccess && lastSuccess > 0 && lastSuccess !== lastCheck && (
        <span className="text-emerald-500/70">
          Last OK {unixTimeAgo(lastSuccess)}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Preference Toggle
// ---------------------------------------------------------------------------

function PreferenceToggle({
  preferredAuth,
  onPreferenceChange,
}: {
  preferredAuth: "oauth" | "api_key";
  onPreferenceChange: (pref: "oauth" | "api_key") => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] text-slate-500">Prefer:</span>
      <div className="flex rounded-md border border-slate-700 overflow-hidden">
        <button
          onClick={() => onPreferenceChange("oauth")}
          className={cn(
            "px-2 py-0.5 text-[10px] font-medium transition-colors",
            preferredAuth === "oauth"
              ? "bg-emerald-600 text-white"
              : "bg-slate-800 text-slate-500 hover:bg-slate-700",
          )}
        >
          OAuth
        </button>
        <button
          onClick={() => onPreferenceChange("api_key")}
          className={cn(
            "px-2 py-0.5 text-[10px] font-medium transition-colors",
            preferredAuth === "api_key"
              ? "bg-blue-600 text-white"
              : "bg-slate-800 text-slate-500 hover:bg-slate-700",
          )}
        >
          API Key
        </button>
      </div>
    </div>
  );
}
