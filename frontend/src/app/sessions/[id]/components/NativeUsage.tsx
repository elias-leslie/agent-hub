import type { TimelineEvent } from '@/types/events'
import { formatTokens } from './utils'

const usageFields = [
  ['input_tokens', 'Input'],
  ['output_tokens', 'Output'],
  ['cached_input_tokens', 'Cached input'],
  ['cache_write_input_tokens', 'Cache write'],
  ['reasoning_output_tokens', 'Reasoning output'],
] as const

type UsageField = (typeof usageFields)[number][0]
type Counts = Record<UsageField, { value: number; recorded: number }>

function validCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function nativeUsage(event: TimelineEvent, scope: string) {
  const usage = event.usage
  return usage?.scope === scope && typeof usage.source === 'string'
    ? usage
    : null
}

function emptyCounts(): Counts {
  return Object.fromEntries(
    usageFields.map(([key]) => [key, { value: 0, recorded: 0 }]),
  ) as Counts
}

export interface NativeUsageSummary {
  responseCount: number
  counts: Counts
  sources: string[]
  latestCounters: Array<{
    scope: 'turn' | 'thread'
    source: string
    timestamp: string | null
    counts: Counts
  }>
}

export function summarizeNativeUsage(
  events: TimelineEvent[],
): NativeUsageSummary {
  const counts = emptyCounts()
  const responseIds = new Set<string>()
  const sources = new Set<string>()
  const counters = new Map<
    'turn' | 'thread',
    NativeUsageSummary['latestCounters'][number]
  >()

  for (const event of events) {
    const response =
      event.event_type === 'usage' ? nativeUsage(event, 'response') : null
    if (response) {
      const identity =
        (typeof response.response_id === 'string' && response.response_id) ||
        event.source_event_id ||
        event.id
      if (responseIds.has(identity)) continue
      responseIds.add(identity)
      sources.add(response.source as string)
      for (const [key] of usageFields) {
        const value = response[key]
        if (validCount(value)) {
          counts[key].value += value
          counts[key].recorded += 1
        }
      }
    }

    if (event.event_type !== 'usage_counter') continue
    const usage = event.usage
    const scope = usage?.scope
    if (scope !== 'turn' && scope !== 'thread') continue
    const counter = nativeUsage(event, scope)
    if (!counter) continue
    const counterCounts = emptyCounts()
    for (const [key] of usageFields) {
      const value = counter[key]
      if (validCount(value)) {
        counterCounts[key] = { value, recorded: 1 }
      }
    }
    counters.set(scope, {
      scope,
      source: counter.source as string,
      timestamp: event.source_timestamp || event.created_at || null,
      counts: counterCounts,
    })
  }

  return {
    responseCount: responseIds.size,
    counts,
    sources: [...sources],
    latestCounters: [...counters.values()],
  }
}

function CountGrid({
  counts,
  denominator,
}: {
  counts: Counts
  denominator: number | null
}) {
  return (
    <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      {usageFields.map(([key, label]) => {
        const count = counts[key]
        return (
          <div key={key} className="detail-card min-w-0">
            <dt className="detail-label">{label}</dt>
            <dd className="mt-2 font-mono text-sm text-slate-200">
              {count.recorded > 0 ? formatTokens(count.value) : 'Unavailable'}
            </dd>
            {denominator !== null && denominator > 0 && (
              <dd className="mt-1 text-xs text-slate-500">
                {count.recorded}/{denominator} response records
              </dd>
            )}
          </div>
        )
      })}
    </dl>
  )
}

export function NativeUsage({
  events,
  totalEvents,
}: {
  events: TimelineEvent[]
  totalEvents: number
}) {
  const summary = summarizeNativeUsage(events)

  return (
    <section
      aria-labelledby="native-usage-heading"
      className="section-card space-y-4"
    >
      <div>
        <h3
          id="native-usage-heading"
          className="text-sm font-medium text-slate-200"
        >
          Native token usage
        </h3>
        <p className="mt-1 text-xs text-slate-400">
          {summary.responseCount > 0
            ? `${summary.responseCount} response record${summary.responseCount === 1 ? '' : 's'} in loaded events. Coverage of all model responses is unknown.`
            : 'No per-response native usage in loaded events.'}{' '}
          Child sessions are not included.
        </p>
        <p className="mt-1 text-xs text-slate-500">
          Inspected {events.length} of {totalEvents} session events.
        </p>
      </div>
      <CountGrid
        counts={summary.counts}
        denominator={summary.responseCount || null}
      />
      {summary.sources.length > 0 && (
        <p className="break-all text-xs text-slate-500">
          Source: {summary.sources.join(', ')}. Reasoning output is part of
          output usage where provided.
        </p>
      )}
      {summary.latestCounters.length > 0 && (
        <div className="space-y-3 border-t border-slate-800/60 pt-4">
          <h4 className="text-sm font-medium text-slate-300">
            Latest cumulative observations
          </h4>
          <p className="text-xs text-slate-500">
            Turn and thread counters are separate observations. They are not
            added to response usage.
          </p>
          {summary.latestCounters.map((counter) => (
            <div key={counter.scope} className="space-y-2">
              <p className="break-all text-xs text-slate-400">
                {counter.scope === 'turn' ? 'Turn' : 'Thread'} ·{' '}
                {counter.source}
                {counter.timestamp ? ` · ${counter.timestamp}` : ''}
              </p>
              <CountGrid counts={counter.counts} denominator={null} />
            </div>
          ))}
        </div>
      )}
      <p className="text-xs text-slate-500">
        Token counts are usage records, not a monetary charge.
      </p>
    </section>
  )
}
