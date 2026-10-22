'use client'

import Link from 'next/link'
import {
  type ActivityCost,
  type ActivityTranscript,
  activitySessionsHref,
} from '@/lib/api/activity-cost'
import { StCommandActivity } from './StCommandActivity'

function adminCharacters(transcript: ActivityTranscript) {
  return (
    transcript.breakdown.find((row) => row.category === 'administration')
      ?.characters ?? 0
  )
}

function percent(value: number | null) {
  return value === null ? 'Unavailable' : `${(value * 100).toFixed(1)}%`
}

export function ActivityAccounting({ activity }: { activity: ActivityCost }) {
  const admin = activity.transcript.breakdown.find(
    (row) => row.category === 'administration',
  )
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4 space-y-2">
          <h3 className="text-sm font-semibold text-slate-100">
            Recorded tokens
          </h3>
          <p className="text-2xl font-semibold text-slate-100 tabular-nums">
            {activity.tokens.denominator.toLocaleString()}
          </p>
          <p className="section-copy">
            {activity.usage.input_tokens.toLocaleString()} input ·{' '}
            {activity.usage.output_tokens.toLocaleString()} output
          </p>
          <p className="section-copy">
            Input includes {activity.usage.cache_read_tokens.toLocaleString()}{' '}
            cache read and {activity.usage.cache_write_tokens.toLocaleString()}{' '}
            cache write tokens. Cache detail covers{' '}
            {activity.usage.cache_detail_input_tokens.toLocaleString()} /{' '}
            {activity.usage.input_tokens.toLocaleString()} input tokens.
          </p>
          <p className="section-copy">
            {percent(activity.tokens.unclassified_share)} with unknown or mixed
            tool evidence. Native usage measures repeated context reads, not
            unique history text. Admin spend and resident context share are
            unavailable.
          </p>
          <Link
            href="/costs"
            className="inline-block text-amber-300 underline focus-ring-amber"
          >
            Open spend and pricing coverage
          </Link>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4 space-y-2">
          <h3 className="text-sm font-semibold text-slate-100">
            Admin transcript estimate
          </h3>
          <p className="text-2xl font-semibold text-slate-100 tabular-nums">
            {adminCharacters(activity.transcript).toLocaleString()} characters ·{' '}
            {percent(admin?.share ?? null)}
          </p>
          <p className="section-copy">
            Share of {activity.transcript.characters.toLocaleString()} sampled
            tool transcript characters: normalized call arguments plus retained
            returned text. Admin includes necessary checks, commits and builds.
          </p>
          <p className="section-copy">
            This estimates text added to history. It does not measure model
            tokens, causal spend or context still resident after compaction.
            Prose, instructions, images, protocol framing and unretained text
            are excluded.
          </p>
          <p className="section-copy">
            {activity.transcript.argument_characters.toLocaleString()} argument
            characters +{' '}
            {activity.transcript.returned_characters.toLocaleString()} returned
            characters. Returned text retained for{' '}
            {activity.transcript.calls_with_returned_text.toLocaleString()} /{' '}
            {(
              activity.transcript.calls_with_returned_text +
              activity.transcript.calls_missing_returned_text
            ).toLocaleString()}{' '}
            sampled calls; missing or opaque text has unknown size.{' '}
            {activity.wrappers_excluded.toLocaleString()} correlated wrappers
            excluded.
          </p>
          <p className="section-copy">
            Unknown or mixed calls:{' '}
            {activity.transcript.breakdown
              .find((row) => row.category === 'unknown')
              ?.characters.toLocaleString()}{' '}
            characters. Shares cover this sampled text only. Ledger totals cover
            the full window; event-only usage may be capped. Ambiguous wrapper
            matches can still duplicate text.
          </p>
        </div>
      </div>
      <StCommandActivity
        commands={activity.st_commands}
        sampleCapped={activity.events_truncated}
      />
      <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4 space-y-2 text-sm text-slate-300">
        <h3 className="font-semibold text-slate-100">Usage sources and gaps</h3>
        {activity.tokens.sources.map((row) => (
          <p key={row.source}>
            {row.source}: {row.tokens.toLocaleString()} tokens ·{' '}
            {row.sessions.toLocaleString()} linked Hub sessions
          </p>
        ))}
        <p>
          One source per Hub session: completion logs, native ledger, then
          response events. Overlapping evidence is excluded; partial histories
          can still omit usage. This is recorded usage, not a reconciled bill.
        </p>
        <p>
          {activity.unmatched_accounting_tokens.toLocaleString()} tokens from{' '}
          {activity.unmatched_accounting_calls.toLocaleString()} accounting
          calls have no matching Hub session. Included in global unknown usage;
          excluded from project, session and task rankings.
        </p>
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="min-w-0 space-y-2">
          <h3 className="text-sm font-semibold text-slate-100">
            Projects by recorded tokens
          </h3>
          <p className="section-copy">
            Showing {activity.project_rankings.length} of{' '}
            {activity.project_rankings_total}. Admin characters are a transcript
            proxy, not allocated usage.
          </p>
          {activity.project_rankings.length === 0 && (
            <p className="section-copy">No Hub projects in this window.</p>
          )}
          {activity.project_rankings.map((row) => (
            <div
              key={row.project_id}
              className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 space-y-1"
            >
              <Link
                href={activitySessionsHref(row.project_id)}
                className="text-sm text-amber-300 underline focus-ring-amber break-words"
              >
                {row.project_id}
              </Link>
              <p className="text-xs text-slate-300">
                {row.tokens.toLocaleString()} tokens ·{' '}
                {row.sessions.toLocaleString()} sessions (
                {row.missing_usage_sessions.toLocaleString()} without usage) ·{' '}
                {adminCharacters(row.transcript).toLocaleString()} admin
                characters
              </p>
            </div>
          ))}
        </div>
        <div className="min-w-0 space-y-2">
          <h3 className="text-sm font-semibold text-slate-100">
            Sessions by recorded tokens
          </h3>
          <p className="section-copy">
            Showing {activity.session_rankings.length} of{' '}
            {activity.session_rankings_total}. Sessions without retained usage
            are labelled unavailable.
          </p>
          {activity.session_rankings.length === 0 && (
            <p className="section-copy">No Hub sessions in this window.</p>
          )}
          {activity.session_rankings.map((row) => (
            <div
              key={row.session_id}
              className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 space-y-1"
            >
              <Link
                href={activitySessionsHref(row.project_id, row.session_id)}
                className="text-sm text-amber-300 underline focus-ring-amber break-all"
              >
                {row.project_id} · {row.session_id}
              </Link>
              <p className="text-xs text-slate-300">
                {row.provider} ·{' '}
                {row.usage_source === 'missing'
                  ? 'Usage unavailable'
                  : `${row.tokens.toLocaleString()} tokens`}{' '}
                · {adminCharacters(row.transcript).toLocaleString()} admin
                characters
              </p>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
