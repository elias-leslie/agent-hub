/** Estimated tool text added once, excluding repeated reads and resident context. */
export interface ContextSplit {
  admin_tokens_estimate: number
  other_tokens_estimate: number
  unknown_tokens_estimate: number
  denominator_tokens_estimate: number
  argument_tokens_estimate: number
  returned_tokens_estimate: number
  admin_share: number | null
  other_share: number | null
  unknown_share: number | null
  tools_sampled: number
  tools_missing_output: number
  tokenized_argument_calls: number
  estimated_argument_calls: number
  events_truncated: boolean
  input_token_encoding: string
  output_characters_per_token: number
}

export function isContextSplit(value: unknown): value is ContextSplit {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    return false
  const row: Record<string, unknown> = value as Record<string, unknown>
  const fields = [
    'admin_tokens_estimate',
    'other_tokens_estimate',
    'unknown_tokens_estimate',
    'denominator_tokens_estimate',
    'argument_tokens_estimate',
    'returned_tokens_estimate',
    'tools_sampled',
    'tools_missing_output',
    'tokenized_argument_calls',
    'estimated_argument_calls',
  ]
  if (
    !fields.every(
      (key) =>
        typeof row[key] === 'number' &&
        Number.isSafeInteger(row[key]) &&
        row[key] >= 0,
    ) ||
    typeof row.events_truncated !== 'boolean' ||
    typeof row.input_token_encoding !== 'string' ||
    typeof row.output_characters_per_token !== 'number' ||
    !Number.isFinite(row.output_characters_per_token) ||
    row.output_characters_per_token <= 0
  )
    return false
  const total = Number(row.denominator_tokens_estimate)
  if (
    Number(row.admin_tokens_estimate) + Number(row.other_tokens_estimate) !==
      total ||
    Number(row.argument_tokens_estimate) +
      Number(row.returned_tokens_estimate) !==
      total ||
    Number(row.unknown_tokens_estimate) > Number(row.other_tokens_estimate) ||
    Number(row.tools_missing_output) > Number(row.tools_sampled) ||
    Number(row.tokenized_argument_calls) +
      Number(row.estimated_argument_calls) >
      Number(row.tools_sampled)
  )
    return false
  return ['admin_share', 'other_share', 'unknown_share'].every((key) =>
    total === 0
      ? row[key] === null
      : typeof row[key] === 'number' &&
        Number.isFinite(row[key]) &&
        row[key] >= 0 &&
        row[key] <= 1 &&
        Math.abs(
          row[key] -
            Number(row[key.replace('_share', '_tokens_estimate')]) / total,
        ) <
          Number.EPSILON * 4,
  )
}

export const contextTokens = (value: number) =>
  `${value.toLocaleString()} est. tokens`
