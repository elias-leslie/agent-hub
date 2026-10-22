'use client'

import Link from 'next/link'
import {
  activitySessionsHref,
  type StCommandMetrics,
  type StCommandSummary,
} from '@/lib/api/activity-cost'

function elapsed(row: StCommandMetrics) {
  return row.commands_with_duration === 0
    ? 'Time unavailable'
    : `${row.measured_seconds.toLocaleString(undefined, { maximumFractionDigits: 1 })}s elapsed`
}

function output(row: StCommandMetrics) {
  return row.commands_with_output === 0
    ? 'Output estimate unavailable'
    : `~${row.output_tokens_estimate.toLocaleString()} output text tokens`
}

const LABELS = {
  administration: 'Admin',
  necessary_support: 'Support',
  substantive: 'Substantive',
  unknown: 'Unknown',
}

export function StCommandActivity({
  commands,
  sampleCapped,
}: {
  commands: StCommandSummary | null | undefined
  sampleCapped: boolean
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4 space-y-3">
      <h3 className="text-sm font-semibold text-slate-100">
        ST command time and text
      </h3>
      {!commands ? (
        <p className="section-copy">
          ST command data is unavailable from this server.
        </p>
      ) : (
        <>
          <p className="text-sm text-slate-100 tabular-nums">
            {commands.commands.toLocaleString()} ST commands in sampled calls ·{' '}
            {elapsed(commands)} · ~
            {commands.input_tokens_estimate.toLocaleString()} input text tokens
            · {output(commands)}
          </p>
          <p className="section-copy">
            {commands.administration_commands.toLocaleString()} admin + support
            · {commands.substantive_commands.toLocaleString()} substantive ·{' '}
            {commands.unknown_commands.toLocaleString()} unknown commands. Text
            estimates describe command input and retained output added once to
            history. They are separate from provider usage, billed tokens and
            context still resident after compaction.
          </p>
          <p className="section-copy">
            Time known for {commands.commands_with_duration}/{commands.commands}
            ; output known for {commands.commands_with_output}/
            {commands.commands}. {commands.shared_commands} commands share shell
            results and may not have run; their time and output stay
            unallocated.
            {sampleCapped &&
              ' Event sample capped; earlier calls may be missing.'}
          </p>
          <p className="section-copy">
            Input tokenized for {commands.commands_with_tokenized_input}/
            {commands.commands} commands; the rest use a character estimate to
            bound refresh cost.
          </p>
          {commands.commands === 0 && (
            <p className="section-copy">
              No recognizable ST commands in the sampled calls. Unrecorded or
              unsupported calls may be missing.
            </p>
          )}
          <details>
            <summary className="cursor-pointer text-sm text-amber-300 focus-ring-amber">
              Top ST families and coverage
            </summary>
            <div className="mt-3 space-y-3">
              <p className="section-copy">
                Showing {commands.families.length} of {commands.families_total}{' '}
                families, ranked by estimated input + output text tokens.
              </p>
              {commands.families.map((row) => (
                <div
                  key={row.family}
                  className="border-t border-slate-800 pt-3 space-y-1"
                >
                  <p className="text-sm font-medium text-slate-100">
                    {row.family} · {LABELS[row.category]}
                  </p>
                  <p className="text-xs text-slate-300 tabular-nums">
                    {row.commands.toLocaleString()}{' '}
                    {row.commands === 1 ? 'command' : 'commands'} ·{' '}
                    {elapsed(row)} · ~
                    {row.input_tokens_estimate.toLocaleString()} input text
                    tokens · {output(row)}
                  </p>
                  <p className="text-xs text-slate-400">
                    Input tokenized for {row.commands_with_tokenized_input}/
                    {row.commands} · time known for {row.commands_with_duration}
                    /{row.commands} · output known for{' '}
                    {row.commands_with_output}/{row.commands}.
                  </p>
                  {row.sample_session_id && row.sample_project_id && (
                    <Link
                      href={activitySessionsHref(
                        row.sample_project_id,
                        row.sample_session_id,
                      )}
                      className="inline-block text-xs text-amber-300 underline focus-ring-amber"
                    >
                      Open an observed {row.family} session
                    </Link>
                  )}
                </div>
              ))}
              <p className="section-copy">
                Concurrent elapsed times add; this differs from merged tool
                occupancy below.
              </p>
              <p className="section-copy">
                {commands.calls_with_st}/{commands.shell_calls} sampled shell
                calls contain recognizable ST commands;{' '}
                {commands.shell_calls_unparsed} shell calls could not be parsed.{' '}
                {commands.unknown_commands} ST commands have unknown class. Only
                direct ST commands in supported shell syntax are counted;
                wrappers, scripts and unsampled events can hide more.
              </p>
              <p className="section-copy">
                Input uses {commands.input_token_encoding} on normalized command
                arguments within tokenizer limits; other input uses characters ÷{' '}
                {commands.output_characters_per_token}, rounded up. Output uses
                retained characters ÷ {commands.output_characters_per_token},
                rounded up per isolated command, matching ST tools cost.
                Language and formatting affect accuracy. Missing or truncated
                text has unknown size. Arguments and output contents are not
                included in this report.
              </p>
            </div>
          </details>
        </>
      )}
    </div>
  )
}
