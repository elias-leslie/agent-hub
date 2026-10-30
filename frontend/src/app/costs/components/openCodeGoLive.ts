import type {
  OpenCodeGoUsage,
  OpenCodeGoWindow,
  ProviderUtilization,
  UsageWindow,
} from '@/lib/api/analytics'

export const OPENCODE_GO = 'opencode-go'

/** A plan-limit window as the card shows it; live OpenCode readings can also say rate limited. */
export type ShownWindow = UsageWindow & { rate_limited?: boolean }

export type ShownProvider = Omit<ProviderUtilization, 'windows'> & {
  windows: ShownWindow[]
  /** One line under the provider: the live reading's caveat or why it is missing. */
  note?: string
}

// Same window lengths and labels the stored readings use (subscription_accounting summary).
const LIVE_WINDOWS: Record<
  OpenCodeGoWindow['key'],
  { minutes: number; label: string }
> = {
  rolling: { minutes: 300, label: '5h' },
  weekly: { minutes: 10080, label: 'weekly' },
  monthly: { minutes: 43200, label: 'monthly' },
}

const LIVE_CAVEAT =
  'Live from an unofficial OpenCode endpoint, which can change without notice.'

/**
 * One OpenCode Go entry in the plan limits: the live reading when OpenCode answers, else the
 * stored reading (shown with its age) plus why live is missing. `live` undefined and not failed
 * means the live request is still loading, so the stored reading shows as is.
 */
export function withLiveOpenCodeGo(
  utilization: ProviderUtilization[],
  live: OpenCodeGoUsage | undefined,
  liveFailed: boolean,
): ShownProvider[] {
  const stored = utilization.find((p) => p.provider === OPENCODE_GO)
  let entry: ShownProvider | undefined = stored
  if (live?.state === 'ok' && live.windows.length > 0) {
    entry = {
      provider: OPENCODE_GO,
      plan_type: stored?.plan_type ?? null,
      // A failed refresh keeps the last answer; say so instead of calling it current.
      note: liveFailed
        ? `Live refresh failed; showing the last live reading. ${LIVE_CAVEAT}`
        : LIVE_CAVEAT,
      windows: live.windows.map((w) => ({
        window_minutes: LIVE_WINDOWS[w.key].minutes,
        label: LIVE_WINDOWS[w.key].label,
        used_percent: w.percent,
        resets_at: w.resets_at,
        observed_at: live.fetched_at,
        reset_since_observed: false,
        source: 'opencode_go_live',
        source_label: 'OpenCode, live',
        rate_limited: w.status === 'rate-limited',
      })),
    }
  } else if (live || liveFailed) {
    const notSetUp = live?.state === 'not_configured'
    const reason = live?.reason ? ` ${live.reason}` : ''
    const note = notSetUp
      ? `Not set up.${reason}`
      : `Live reading unavailable.${reason}`
    entry = {
      provider: OPENCODE_GO,
      plan_type: stored?.plan_type ?? null,
      windows: stored?.windows ?? [],
      note,
    }
  }
  const others = utilization.filter((p) => p.provider !== OPENCODE_GO)
  return entry ? [...others, entry] : others
}
