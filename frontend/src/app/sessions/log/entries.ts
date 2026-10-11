import type { TimelineEvent } from '@/types/events'

/**
 * Turns raw session events into one-line log entries a person can scan.
 * Tool calls merge with their results, harness scaffolding collapses into a
 * context line, and Codex exec wrappers that only mirror a Bash call are hidden.
 */

export type LogKind =
  | 'prompt'
  | 'agent'
  | 'context'
  | 'tool'
  | 'error'
  | 'thinking'
  | 'usage'
  | 'memory'

export type LogDetail =
  | { type: 'text'; text: string }
  | { type: 'output'; text: string; truncated: boolean }
  | { type: 'diff'; lines: string[] }

export interface LogEntry {
  id: string
  turn: number
  /** ISO timestamp of the first source event. */
  at: string
  kind: LogKind
  /** Short type label shown in the gutter: you, agent, ran, edited, … */
  label: string
  /** One-line human summary. */
  summary: string
  /** Outcome or size: "exit 0 · 3.2s", "+9 −2", "6 matches". */
  meta?: string
  failed?: boolean
  detail?: LogDetail
  /** Source events, for the Raw view. */
  raw: TimelineEvent[]
}

export const OUTPUT_TAIL_LINES = 40
const SUMMARY_MAX = 240

type Json = Record<string, unknown>

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null
}

function oneLine(text: string, max = SUMMARY_MAX): string {
  const collapsed = text.replace(/\s+/g, ' ').trim()
  return collapsed.length > max ? `${collapsed.slice(0, max - 1)}…` : collapsed
}

function lineCount(text: string): number {
  if (!text) return 0
  return text.replace(/\n$/, '').split('\n').length
}

function tail(text: string): LogDetail {
  const lines = text.replace(/\n+$/, '').split('\n')
  if (lines.length <= OUTPUT_TAIL_LINES)
    return { type: 'output', text: lines.join('\n'), truncated: false }
  return {
    type: 'output',
    text: lines.slice(-OUTPUT_TAIL_LINES).join('\n'),
    truncated: true,
  }
}

/** Pulls a string field out of JSON that was cut off before it closed. */
function salvageField(text: string, field: string): string | null {
  const match = new RegExp(`"${field}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)`).exec(
    text,
  )
  if (!match) return null
  const body = match[1].replace(/\\(u[0-9a-fA-F]{0,3})?$/, '')
  try {
    return JSON.parse(`"${body}"`) as string
  } catch {
    return body.replace(/\\n/g, '\n').replace(/\\"/g, '"')
  }
}

function parseMaybeJson(value: unknown): unknown {
  if (typeof value !== 'string') return value
  const trimmed = value.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return value
  try {
    return JSON.parse(trimmed)
  } catch {
    return value
  }
}

export function formatDuration(ms: number | null | undefined): string | null {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0)
    return null
  if (ms < 1000) return `${Math.round(ms)}ms`
  const seconds = ms / 1000
  if (seconds < 60)
    return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  if (minutes < 60) return rest ? `${minutes}m ${rest}s` : `${minutes}m`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

/* ---------- harness scaffolding ---------- */

const LEADING_TAG = /^\s*<([a-z][a-z0-9_-]*)(\s[^>]*)?>/i

function scaffoldName(text: string): string | null {
  const trimmed = text.trimStart()
  if (trimmed.startsWith('# AGENTS.md instructions')) return 'AGENTS.md'
  if (trimmed.startsWith('# CLAUDE.md')) return 'CLAUDE.md'
  if (trimmed.startsWith('The following is the Codex agent history'))
    return 'Codex history'
  const tag = LEADING_TAG.exec(trimmed)
  if (tag) return tag[1].replace(/[_-]+/g, ' ')
  return null
}

/**
 * Splits leading harness blocks from a message. Returns the block names and
 * whatever the person actually wrote after them (may be empty).
 */
export function splitScaffold(text: string): {
  names: string[]
  rest: string
} {
  const names: string[] = []
  let rest = text
  for (let guard = 0; guard < 8; guard += 1) {
    const name = scaffoldName(rest)
    if (!name) break
    names.push(name)
    const tag = LEADING_TAG.exec(rest.trimStart())
    if (tag) {
      const close = new RegExp(`</${tag[1]}\\s*>`, 'i')
      const body = rest.trimStart()
      const match = close.exec(body)
      if (!match) return { names, rest: '' }
      rest = body.slice(match.index + match[0].length)
      continue
    }
    // Markdown preambles run to the end of the message.
    return { names, rest: '' }
  }
  return { names, rest: rest.trim() }
}

/* ---------- tool formatting ---------- */

interface ToolOutput {
  text: string
  exitCode: number | null
  failed: boolean
  /** Edit payload from Claude Code results. */
  oldString?: string
  newString?: string
  structured?: Json
}

function exitFromText(text: string): number | null {
  const match = /^Exit code (\d+)/.exec(text)
  return match ? Number(match[1]) : null
}

function readOutput(
  use: TimelineEvent | null,
  result: TimelineEvent | null,
): ToolOutput {
  const sources = [result?.tool_output, use?.tool_output].filter(isObject)
  let text = ''
  let exitCode: number | null = null
  let failed = false
  let structured: Json | undefined

  for (const source of sources) {
    if (typeof source.exit_code === 'number') exitCode = source.exit_code
    if (source.is_error === true || source.status === 'failed') failed = true
    let parsed = parseMaybeJson(source.result)
    // Long Claude Code outputs are stored cut off, so the JSON never closes.
    if (
      typeof parsed === 'string' &&
      /^\s*\{\s*"(stdout|filePath)"/.test(parsed)
    ) {
      const stdout = salvageField(parsed, 'stdout')
      const stderr = salvageField(parsed, 'stderr')
      if (stdout !== null || stderr !== null)
        parsed = { stdout: stdout ?? '', stderr: stderr ?? '' }
    }
    const body = isObject(parsed) ? parsed : source
    if (isObject(parsed)) structured = parsed
    const pieces = [
      str(body.stdout),
      str(body.stderr),
      str(body.output),
      typeof parsed === 'string' ? parsed : null,
      str(source.content),
    ].filter((piece): piece is string => piece !== null)
    if (!text && pieces.length) text = pieces.join('\n')
    if (typeof body.exit_code === 'number') exitCode = body.exit_code
    if (body.interrupted === true) failed = true
  }
  if (!text && result?.content) text = result.content
  if (exitCode === null) exitCode = exitFromText(text)
  if (exitCode !== null && exitCode !== 0) failed = true

  return {
    text,
    exitCode,
    failed,
    oldString: str(structured?.oldString) ?? undefined,
    newString: str(structured?.newString) ?? undefined,
    structured,
  }
}

function bashCommand(input: Json): string {
  const command = input.command ?? input.cmd
  let text = ''
  if (Array.isArray(command)) {
    const parts = command.filter(
      (part): part is string => typeof part === 'string',
    )
    const flag = parts.findIndex((part) => part === '-lc' || part === '-c')
    text = flag >= 0 && parts[flag + 1] ? parts[flag + 1] : parts.join(' ')
  } else if (typeof command === 'string') {
    text = command
  }
  // A leading "cd <dir>;" or "cd <dir> &&" only sets the stage.
  return text.replace(/^\s*cd\s+("[^"]*"|'[^']*'|\S+)\s*(&&|;)\s*/, '').trim()
}

function lineDiff(oldText: string, newText: string) {
  const a = oldText.split('\n')
  const b = newText.split('\n')
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start])
    start += 1
  let endA = a.length - 1
  let endB = b.length - 1
  while (endA >= start && endB >= start && a[endA] === b[endB]) {
    endA -= 1
    endB -= 1
  }
  const removed = a.slice(start, endA + 1)
  const added = b.slice(start, endB + 1)
  return {
    removed: removed.length,
    added: added.length,
    lines: [
      ...a.slice(Math.max(0, start - 2), start).map((line) => ` ${line}`),
      ...removed.map((line) => `-${line}`),
      ...added.map((line) => `+${line}`),
    ],
  }
}

function patchStats(patch: string) {
  const lines = patch.split('\n')
  const files = lines
    .map((line) => /^\*\*\* (?:Update|Add|Delete) File: (.+)$/.exec(line)?.[1])
    .filter((file): file is string => Boolean(file))
  const added = lines.filter(
    (line) => line.startsWith('+') && !line.startsWith('+++'),
  ).length
  const removed = lines.filter(
    (line) => line.startsWith('-') && !line.startsWith('---'),
  ).length
  return { files, added, removed, lines }
}

function shortPath(path: string): string {
  return path.replace(/^\/srv\/workspaces\/projects\/[^/]+\//, '')
}

function genericSummary(input: Json | null): string {
  if (!input) return ''
  const parts: string[] = []
  for (const [key, value] of Object.entries(input)) {
    if (key === 'call_id' || key === 'message' || value === null) continue
    if (
      typeof value === 'string' ||
      typeof value === 'number' ||
      typeof value === 'boolean'
    )
      parts.push(`${key}: ${value}`)
    if (parts.length >= 3) break
  }
  return parts.join(' · ')
}

function joinMeta(
  ...parts: Array<string | null | undefined | false>
): string | undefined {
  const kept = parts.filter((part): part is string => Boolean(part))
  return kept.length ? kept.join(' · ') : undefined
}

/* ---------- inter-agent envelopes ---------- */

export interface Envelope {
  type: string
  task: string | null
  sender: string | null
  payload: string
}

/** Codex multi-agent messages: "Message Type: X / Task name / Sender / Payload". */
export function parseEnvelope(text: string): Envelope | null {
  const match = /^\s*Message Type: ([A-Z_]+)\s*\n([\s\S]*)$/.exec(text)
  if (!match) return null
  const body = match[2]
  const field = (name: string) =>
    new RegExp(`^${name}:[ \\t]*(.*)$`, 'm').exec(body)?.[1]?.trim() || null
  const payloadAt = body.search(/^Payload:/m)
  const payload =
    payloadAt >= 0 ? body.slice(payloadAt + 'Payload:'.length).trim() : ''
  return {
    type: match[1],
    task: field('Task name'),
    sender: field('Sender'),
    payload,
  }
}

function agentName(path: string | null): string {
  if (!path) return 'agent'
  if (path === '/root') return 'parent'
  return path.replace(/^\/root\//, '')
}

/* ---------- Codex exec wrappers ---------- */

interface ExecScript {
  calls: string[]
  commands: string[]
  patch: string | null
  /** First web search query, when the script searches the web. */
  webQuery: string | null
}

/** Reads which tools a Codex exec wrapper script calls. */
export function parseExecScript(raw: string): ExecScript {
  const calls = [...raw.matchAll(/tools\.([a-z_]+)\s*\(/g)].map((m) => m[1])
  const commands = [...raw.matchAll(/\bcmd\s*:\s*("(?:[^"\\]|\\.)*")/g)]
    .map((m) => {
      try {
        return JSON.parse(m[1]) as string
      } catch {
        return m[1].slice(1, -1)
      }
    })
    .map((cmd) => cmd.trim())
  const literal = /("\*\*\* Begin Patch(?:[^"\\]|\\.)*")/.exec(raw)?.[1]
  let patch: string | null = null
  if (literal) {
    try {
      patch = JSON.parse(literal) as string
    } catch {
      patch = literal.slice(1, -1).replace(/\\n/g, '\n')
    }
  }
  let webQuery: string | null = null
  const q = /"q"\s*:\s*("(?:[^"\\]|\\.)*")/.exec(raw)?.[1]
  if (q && calls.some((call) => call.startsWith('web'))) {
    try {
      webQuery = JSON.parse(q) as string
    } catch {
      webQuery = q.slice(1, -1)
    }
  }
  return { calls, commands, patch, webQuery }
}

function toolEntry(use: TimelineEvent, result: TimelineEvent | null): LogEntry {
  const name = use.tool_name ?? 'tool'
  const input = isObject(use.tool_input) ? use.tool_input : {}
  const out = readOutput(use, result)
  const duration = formatDuration(result?.duration_ms ?? use.duration_ms)
  const exit = out.exitCode !== null ? `exit ${out.exitCode}` : null
  const raw = result ? [use, result] : [use]
  const base: Pick<LogEntry, 'id' | 'turn' | 'at' | 'kind' | 'failed' | 'raw'> =
    {
      id: use.id,
      turn: use.turn,
      at: use.source_timestamp ?? use.created_at,
      kind: 'tool',
      failed: out.failed,
      raw,
    }
  const outputDetail = out.text ? tail(out.text) : undefined

  if (name === 'exec' && typeof input.raw === 'string') {
    const script = parseExecScript(input.raw)
    if (script.patch) {
      const stats = patchStats(script.patch)
      return {
        ...base,
        label: 'edited',
        summary: stats.files.map(shortPath).join(', ') || 'patch',
        meta: `+${stats.added} −${stats.removed}`,
        detail: { type: 'diff', lines: stats.lines },
      }
    }
    if (
      script.calls.length &&
      script.calls.every((call) => call === 'write_stdin')
    )
      return {
        ...base,
        kind: 'context',
        label: 'polled',
        summary: 'running shell',
        failed: false,
      }
    if (script.webQuery)
      return {
        ...base,
        label: 'searched',
        summary: oneLine(`web: ${script.webQuery}`),
        meta: script.commands.length
          ? `+${script.commands.length} command${script.commands.length === 1 ? '' : 's'}`
          : undefined,
        detail: outputDetail,
      }
    if (!script.commands.length && script.calls.length) {
      const counts = new Map<string, number>()
      for (const call of script.calls)
        counts.set(call, (counts.get(call) ?? 0) + 1)
      return {
        ...base,
        label: 'tool',
        summary: [...counts]
          .map(([call, n]) => (n > 1 ? `${call} ×${n}` : call))
          .join(', '),
        meta: joinMeta(duration),
        detail: outputDetail,
      }
    }
    if (script.commands.length)
      return {
        ...base,
        label: 'ran',
        summary: oneLine(script.commands.join(' ; ')),
        meta: joinMeta(exit, duration),
        detail: outputDetail,
      }
  }

  switch (name) {
    case 'Bash':
    case 'exec_command':
    case 'shell':
    case 'local_shell': {
      const command = bashCommand(input)
      const isSearch = /^(rg|grep|ag|fd|find)\b/.test(command)
      const lines = lineCount(out.text)
      // rg and grep exit 1 when nothing matched; that is an answer, not a failure.
      const noMatch = isSearch && out.exitCode === 1 && !out.text.trim()
      return {
        ...base,
        failed: out.failed && !noMatch,
        label: isSearch ? 'searched' : 'ran',
        summary: oneLine(command || genericSummary(input)),
        meta: joinMeta(
          noMatch ? 'no matches' : exit,
          duration,
          isSearch && lines ? `${lines} line${lines === 1 ? '' : 's'}` : null,
        ),
        detail: outputDetail,
      }
    }
    case 'Edit':
    case 'MultiEdit': {
      const path = str(input.file_path) ?? str(out.structured?.filePath) ?? ''
      const oldText = str(input.old_string) ?? out.oldString
      const newText = str(input.new_string) ?? out.newString
      if (oldText !== undefined || newText !== undefined) {
        const diff = lineDiff(oldText ?? '', newText ?? '')
        return {
          ...base,
          label: 'edited',
          summary: shortPath(path),
          meta: `+${diff.added} −${diff.removed}`,
          detail: { type: 'diff', lines: diff.lines },
        }
      }
      return {
        ...base,
        label: 'edited',
        summary: shortPath(path),
        detail: outputDetail,
      }
    }
    case 'apply_patch': {
      const patch = str(input.patch) ?? str(input.input) ?? str(input.raw) ?? ''
      const stats = patchStats(patch)
      return {
        ...base,
        label: 'edited',
        summary: stats.files.map(shortPath).join(', ') || 'patch',
        meta: `+${stats.added} −${stats.removed}`,
        detail: { type: 'diff', lines: stats.lines },
      }
    }
    case 'Write': {
      const content = str(input.content) ?? ''
      return {
        ...base,
        label: 'wrote',
        summary: shortPath(str(input.file_path) ?? ''),
        meta: content ? `${lineCount(content)} lines` : undefined,
        detail: content ? tail(content) : outputDetail,
      }
    }
    case 'Read': {
      const path = str(input.file_path) ?? ''
      const image = /\.(png|jpe?g|gif|webp)$/i.test(path)
      const lines = lineCount(out.text)
      return {
        ...base,
        label: 'read',
        summary: shortPath(path),
        meta: image ? 'image' : lines ? `${lines} lines` : undefined,
        detail: image ? undefined : outputDetail,
      }
    }
    case 'Grep':
    case 'Glob': {
      const pattern = str(input.pattern) ?? ''
      const where = str(input.path)
      const lines = lineCount(out.text)
      return {
        ...base,
        label: 'searched',
        summary: oneLine(
          `"${pattern}"${where ? ` in ${shortPath(where)}` : ''}`,
        ),
        meta: lines ? `${lines} result${lines === 1 ? '' : 's'}` : undefined,
        detail: outputDetail,
      }
    }
    case 'WebFetch':
      return {
        ...base,
        label: 'fetched',
        summary: oneLine(str(input.url) ?? ''),
        detail: outputDetail,
      }
    case 'WebSearch':
      return {
        ...base,
        label: 'searched',
        summary: oneLine(`web: ${str(input.query) ?? ''}`),
        detail: outputDetail,
      }
    case 'Agent':
    case 'Task': {
      const what =
        str(input.description) ??
        str(input.subagent_type) ??
        oneLine(str(input.prompt) ?? '', 80)
      return {
        ...base,
        label: 'spawned',
        summary: oneLine(what),
        detail: outputDetail,
      }
    }
    case 'spawn_agent': {
      const fromResult = parseMaybeJson(result?.content)
      const task = isObject(fromResult) ? str(fromResult.task_name) : null
      return {
        ...base,
        label: 'spawned',
        summary: task ? task.replace(/^\/root\//, '') : 'sub-agent',
        meta: joinMeta(str(input.model)),
      }
    }
    case 'wait_agent':
    case 'wait': {
      const parsed = parseMaybeJson(result?.content)
      const timedOut = isObject(parsed) && parsed.timed_out === true
      return {
        ...base,
        label: 'waited',
        summary: 'for sub-agents',
        meta: joinMeta(timedOut ? 'timed out' : null, duration),
      }
    }
    case 'send_message':
    case 'followup_task':
    case 'SendMessage': {
      const target =
        str(input.target) ?? str(input.to) ?? str(input.recipient) ?? 'agent'
      return {
        ...base,
        label: 'messaged',
        summary: target.startsWith('uds:')
          ? `local session ${
              target
                .split('/')
                .pop()
                ?.replace(/\.sock$/, '') ?? ''
            }`
          : agentName(target),
      }
    }
    case 'sleep':
      return {
        ...base,
        label: 'waited',
        summary: formatDuration(Number(input.duration_ms)) ?? 'sleep',
      }
    case 'Skill':
      return { ...base, label: 'skill', summary: str(input.skill) ?? '' }
    case 'ToolSearch':
      return {
        ...base,
        label: 'tools',
        summary: oneLine(str(input.query) ?? ''),
      }
    default: {
      const summary =
        name === 'exec' || name === 'js'
          ? oneLine(str(input.raw) ?? genericSummary(input))
          : genericSummary(input)
      return {
        ...base,
        label: name.length > 9 ? 'tool' : name,
        summary:
          name.length > 9
            ? [name, summary].filter(Boolean).join(' · ')
            : summary || name,
        meta: joinMeta(exit, duration),
        detail: outputDetail,
      }
    }
  }
}

/* ---------- messages ---------- */

function approvalSummary(text: string): string | null {
  const parsed = parseMaybeJson(text)
  if (!isObject(parsed) || typeof parsed.outcome !== 'string') return null
  const risk = str(parsed.risk_level)
  const why = str(parsed.rationale)
  return `approval ${parsed.outcome}${risk ? ` · ${risk} risk` : ''}${why ? ` · ${oneLine(why, 160)}` : ''}`
}

function usageSummary(event: TimelineEvent): string {
  const usage = isObject(event.usage)
    ? event.usage
    : isObject(event.tool_output)
      ? event.tool_output
      : {}
  const pick = (...keys: string[]) => {
    for (const key of keys)
      if (typeof usage[key] === 'number') return usage[key] as number
    return null
  }
  const input = pick('input_tokens', 'prompt_tokens')
  const output = pick('output_tokens', 'completion_tokens')
  const cached = pick('cached_input_tokens', 'cache_read_input_tokens')
  const parts = [
    input !== null ? `in ${input.toLocaleString()}` : null,
    output !== null ? `out ${output.toLocaleString()}` : null,
    cached ? `cached ${cached.toLocaleString()}` : null,
  ].filter(Boolean)
  return parts.length
    ? parts.join(' · ')
    : oneLine(event.content ?? 'usage recorded')
}

function textEntry(
  event: TimelineEvent,
  kind: LogKind,
  label: string,
  text: string,
  failed = false,
): LogEntry {
  const summary = oneLine(text)
  return {
    id: event.id,
    turn: event.turn,
    at: event.source_timestamp ?? event.created_at,
    kind,
    label,
    summary,
    failed,
    detail:
      summary.length < text.trim().length || text.includes('\n')
        ? { type: 'text', text: text.trim() }
        : undefined,
    raw: [event],
  }
}

/** Child-session bookkeeping is shown from the sub-agent list instead. */
const SKIPPED_TYPES = new Set([
  'child_session_started',
  'child_session_update',
  'child_session_result',
  'usage_counter',
])

const WRAPPER_TOOLS = new Set(['exec', 'exec_command'])

function resultKey(event: TimelineEvent): string | null {
  if (event.call_id) return event.call_id
  const output = isObject(event.tool_output) ? event.tool_output : null
  return str(output?.tool_use_id) ?? str(output?.call_id)
}

/** Builds log entries from events in chronological order. */
export function buildLogEntries(
  events: readonly TimelineEvent[],
  options: { fromStart?: boolean } = {},
): LogEntry[] {
  const uses = new Map<string, TimelineEvent>()
  const results = new Map<string, TimelineEvent>()
  const wrapperIds = new Set<string>()
  const bashCommands = new Set<string>()
  for (const event of events) {
    if (event.event_type === 'tool_use') {
      if (event.call_id) uses.set(event.call_id, event)
      const input = isObject(event.tool_input) ? event.tool_input : null
      const wrapper = str(input?.wrapper_candidate_call_id)
      if (wrapper) wrapperIds.add(wrapper)
      if (event.tool_name === 'Bash' && input)
        bashCommands.add(bashCommand(input))
    } else if (event.event_type === 'tool_result') {
      const key = resultKey(event)
      if (key && !results.has(key)) results.set(key, event)
    }
  }
  // A wrapper is hidden only when everything it ran is already shown as Bash.
  const hiddenWrappers = new Set<string>()
  for (const [key, event] of uses) {
    if (!WRAPPER_TOOLS.has(event.tool_name ?? '')) continue
    const raw = isObject(event.tool_input) ? str(event.tool_input.raw) : null
    if (!raw) {
      if (wrapperIds.has(key)) hiddenWrappers.add(key)
      continue
    }
    const script = parseExecScript(raw)
    // Incidental calls (clock reads and the like) don't make it more than a mirror.
    const runsCommands =
      script.calls.includes('exec_command') && script.commands.length > 0
    // Polling (write_stdin) and clock reads add nothing; a web search does.
    if (!runsCommands || script.patch || script.webQuery) continue
    if (
      wrapperIds.has(key) ||
      script.commands.every((cmd) => bashCommands.has(cmd))
    )
      hiddenWrappers.add(key)
  }

  // Claude Code hooks and transcript sync can both record one call: the same
  // tool and input seconds apart, one of them without a call_id. Keep one.
  const duplicates = new Set<string>()
  const recent = new Map<string, TimelineEvent>()
  for (const event of events) {
    if (
      event.event_type !== 'tool_use' ||
      WRAPPER_TOOLS.has(event.tool_name ?? '')
    )
      continue
    const input = isObject(event.tool_input) ? event.tool_input : {}
    // Copies differ in incidental fields (timeout, description), so compare
    // what identifies the call.
    const key =
      str(input.command) ??
      str(input.file_path) ??
      str(input.pattern) ??
      str(input.url) ??
      str(input.query) ??
      JSON.stringify(input)
    const signature = `${event.tool_name}\u0000${key}`
    const at = Date.parse(event.source_timestamp ?? event.created_at)
    const prior = recent.get(signature)
    const priorAt = prior
      ? Date.parse(prior.source_timestamp ?? prior.created_at)
      : Number.NaN
    if (
      prior &&
      Math.abs(at - priorAt) <= 5000 &&
      (!prior.call_id || !event.call_id)
    ) {
      // Prefer the copy that carries a call_id (it pairs with its result).
      duplicates.add(prior.call_id ? event.id : prior.id)
      if (!prior.call_id) recent.set(signature, event)
      continue
    }
    recent.set(signature, event)
  }

  const entries: LogEntry[] = []
  for (const event of events) {
    const type = event.event_type
    if (SKIPPED_TYPES.has(type)) continue
    if (duplicates.has(event.id)) continue
    const text = event.content ?? ''

    if (type === 'tool_use') {
      const key = event.call_id
      if (key && hiddenWrappers.has(key)) continue
      entries.push(toolEntry(event, key ? (results.get(key) ?? null) : null))
      continue
    }
    if (type === 'tool_result') {
      const key = resultKey(event)
      if (key && (uses.has(key) || wrapperIds.has(key))) continue
      // Wrapper script receipts carry nothing the Bash rows don't.
      if (/^Script completed/.test(text)) continue
      // Result whose call is outside the loaded window or unrecorded.
      const out = readOutput(null, event)
      const parsedResult = parseMaybeJson(out.text || text)
      if (isObject(parsedResult)) {
        const task = str(parsedResult.task_name)
        entries.push({
          ...textEntry(
            event,
            'tool',
            'result',
            task
              ? `sub-agent ${agentName(task)}`
              : genericSummary(parsedResult) || 'tool result',
            out.failed,
          ),
          detail: { type: 'text', text: JSON.stringify(parsedResult, null, 2) },
        })
        continue
      }
      entries.push({
        ...textEntry(
          event,
          'tool',
          'result',
          out.text || text || 'tool result',
          out.failed,
        ),
        detail: out.text ? tail(out.text) : undefined,
      })
      continue
    }
    const envelope = parseEnvelope(text)
    if (
      envelope &&
      (type === 'user_message' || type === ('subagent_result' as string))
    ) {
      const from = agentName(envelope.sender)
      if (envelope.type === 'NEW_TASK')
        entries.push(
          textEntry(
            event,
            'prompt',
            'task',
            envelope.payload || agentName(envelope.task),
          ),
        )
      else if (
        envelope.type === 'FINAL_ANSWER' ||
        type === ('subagent_result' as string)
      )
        entries.push(
          textEntry(event, 'agent', 'answer', `${from}: ${envelope.payload}`),
        )
      else
        entries.push(
          textEntry(event, 'prompt', 'message', `${from}: ${envelope.payload}`),
        )
      continue
    }
    if (type === ('tool_audit' as string)) {
      const parsed = parseMaybeJson(text)
      const audit = isObject(parsed)
        ? parsed
        : isObject(event.tool_output)
          ? event.tool_output
          : {}
      const summary = [
        str(audit.agent_slug),
        str(audit.execution_status),
        typeof audit.turns_completed === 'number'
          ? `${audit.turns_completed} turns`
          : null,
        str(audit.execution_error),
      ]
        .filter(Boolean)
        .join(' · ')
      entries.push({
        ...textEntry(
          event,
          'context',
          'audit',
          summary || 'run audit',
          !!str(audit.execution_error),
        ),
        detail: { type: 'text', text: JSON.stringify(audit, null, 2) },
      })
      continue
    }
    if (type === 'user_message') {
      const { names, rest } = splitScaffold(text)
      if (names.length)
        entries.push({
          ...textEntry(
            event,
            'context',
            'context',
            `injected: ${names.join(', ')}`,
          ),
          id: `${event.id}:context`,
          detail: { type: 'text', text: text.trim() },
        })
      if (rest) entries.push(textEntry(event, 'prompt', 'you', rest))
      else if (!names.length && text.trim())
        entries.push(textEntry(event, 'prompt', 'you', text))
      continue
    }
    if (type === 'assistant_message') {
      const approval = approvalSummary(text)
      if (approval) {
        entries.push({
          ...textEntry(event, 'agent', 'agent', approval),
          detail: { type: 'text', text },
        })
        continue
      }
      const { names } = splitScaffold(text)
      if (names.length) {
        entries.push({
          ...textEntry(
            event,
            'context',
            'context',
            `injected: ${names.join(', ')}`,
          ),
          detail: { type: 'text', text: text.trim() },
        })
        continue
      }
      if (text.trim()) entries.push(textEntry(event, 'agent', 'agent', text))
      continue
    }
    if (type === 'system_message') {
      const { names } = splitScaffold(text)
      entries.push({
        ...textEntry(
          event,
          'context',
          'system',
          names.length ? `injected: ${names.join(', ')}` : text,
        ),
        detail: { type: 'text', text: text.trim() },
      })
      continue
    }
    if (type === 'thinking') {
      if (text.trim())
        entries.push(textEntry(event, 'thinking', 'thinking', text))
      continue
    }
    if (type === 'usage') {
      entries.push(textEntry(event, 'usage', 'usage', usageSummary(event)))
      continue
    }
    if (type === 'memory_inject' || type === 'memory_cite') {
      entries.push(
        textEntry(
          event,
          'memory',
          type === 'memory_cite' ? 'cited' : 'memory',
          text || 'memory',
        ),
      )
      continue
    }
    if (type === 'error') {
      entries.push(textEntry(event, 'error', 'error', text || 'error', true))
      continue
    }
    if (type === 'child_session_blocked') {
      entries.push(
        textEntry(event, 'error', 'blocked', text || 'sub-agent blocked', true),
      )
      continue
    }
    if (text.trim())
      entries.push(textEntry(event, 'context', type.slice(0, 9), text))
  }
  return tidyContext(byTime(entries), options.fromStart ?? false)
}

/**
 * Orders entries by their own time. Long commands are recorded when they
 * finish but stamped with their start, so recorded order can run backwards.
 */
function byTime(entries: LogEntry[]): LogEntry[] {
  return entries
    .map((entry, index) => ({ entry, index, at: Date.parse(entry.at) }))
    .sort((a, b) => {
      if (Number.isNaN(a.at) || Number.isNaN(b.at)) return a.index - b.index
      return a.at - b.at || a.index - b.index
    })
    .map(({ entry }) => entry)
}

function contextName(text: string): string {
  const scaffold = scaffoldName(text)
  if (scaffold) return scaffold
  const first = text
    .trim()
    .split('\n')[0]
    .replace(/^#+\s*/, '')
  return oneLine(first, 40)
}

/**
 * Harnesses record their own instructions as assistant messages before the
 * first prompt; agents never speak first, so when the log starts at the
 * beginning those become context. Consecutive context lines then merge.
 */
function tidyContext(entries: LogEntry[], fromStart: boolean): LogEntry[] {
  let seenPrompt = !fromStart
  const relabelled = entries.map((entry) => {
    if (entry.kind === 'prompt') seenPrompt = true
    if (seenPrompt || entry.kind !== 'agent') return entry
    const text = entry.raw[0]?.content ?? entry.summary
    return {
      ...entry,
      kind: 'context' as const,
      label: 'context',
      summary: `injected: ${contextName(text)}`,
      detail: { type: 'text' as const, text: text.trim() },
    }
  })

  const merged: LogEntry[] = []
  for (const entry of relabelled) {
    const last = merged[merged.length - 1]
    if (
      last &&
      last.kind === 'context' &&
      entry.kind === 'context' &&
      last.label === 'context' &&
      entry.label === 'context' &&
      last.turn === entry.turn
    ) {
      const names = entry.summary.replace(/^injected: /, '')
      const detailText = [last.detail, entry.detail]
        .map((detail) => (detail?.type === 'text' ? detail.text : ''))
        .filter(Boolean)
        .join('\n\n────────\n\n')
      merged[merged.length - 1] = {
        ...last,
        summary: `${last.summary}, ${names}`,
        detail: detailText ? { type: 'text', text: detailText } : last.detail,
        raw: [...last.raw, ...entry.raw],
      }
      continue
    }
    merged.push(entry)
  }
  return merged
}
