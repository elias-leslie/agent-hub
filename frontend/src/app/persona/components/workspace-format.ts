// --- Formatting helpers ---

export function formatDayLabel(date: Date): string {
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export function formatTimeLabel(date: Date): string {
  return date.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function formatTimestampTitle(date: Date): string {
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function formatDurationLabel(durationMs: number | null): string | null {
  if (durationMs == null) return null
  if (durationMs < 1000) return `${durationMs}ms`
  if (durationMs < 60_000) return `${(durationMs / 1000).toFixed(1)}s`
  const minutes = Math.floor(durationMs / 60_000)
  const seconds = Math.floor((durationMs % 60_000) / 1000)
  return `${minutes}m ${seconds}s`
}

export function formatRuntimeLabel(seconds: number | null): string | null {
  if (seconds == null) return null
  if (seconds < 60) return `${seconds}s median`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m median`
  return `${(seconds / 3600).toFixed(1)}h median`
}

export function shortenText(value: string, maxLength = 88): string {
  if (value.length <= maxLength) return value
  return `${value.slice(0, maxLength - 1)}\u2026`
}

// --- Text processing ---

export function normalizeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim().toLowerCase()
}

export function unescapeDisplayText(value: string): string {
  return value
    .replace(/\\n/g, '\n')
    .replace(/\\"/g, '"')
    .replace(/\\'/g, "'")
    .replace(/\\\\/g, '\\')
}

export function extractWrappedTextPayload(value: string): string | null {
  const keyMatch = /['"]text['"]\s*:/.exec(value)
  if (!keyMatch) return null
  let index = keyMatch.index + keyMatch[0].length
  while (index < value.length && /\s/.test(value[index])) index += 1
  const quote = value[index]
  if (quote !== '"' && quote !== "'") return null
  index += 1
  let escaped = false
  let result = ''
  for (; index < value.length; index += 1) {
    const char = value[index]
    if (escaped) {
      result += char
      escaped = false
      continue
    }
    if (char === '\\') {
      result += char
      escaped = true
      continue
    }
    if (char === quote) break
    result += char
  }
  const unescaped = unescapeDisplayText(result).trim()
  return unescaped || null
}

export function humanizeTaskContextText(value: string): string {
  const lines = value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (!lines.some((line) => line.startsWith('TASK:task-'))) return value

  const prettified: string[] = []
  for (const line of lines) {
    if (line.startsWith('TASK:')) {
      const [taskId, status, priority, taskType, size] = line
        .slice(5)
        .split('|')
      prettified.push(
        `Task ${taskId}${status ? ` \u00b7 ${status}` : ''}${priority ? ` \u00b7 ${priority}` : ''}${taskType ? ` \u00b7 ${taskType}` : ''}${size ? ` \u00b7 ${size}` : ''}`,
      )
      continue
    }
    if (line.startsWith('TITLE:')) {
      prettified.push(`Title: ${line.slice(6).trim()}`)
      continue
    }
    if (line.startsWith('DESCRIPTION:')) {
      prettified.push(`Description: ${line.slice(12).trim()}`)
      continue
    }
    if (line.startsWith('OBJECTIVE:')) {
      prettified.push(`Description: ${line.slice(10).trim()}`)
      continue
    }
    if (line.startsWith('SPIRIT_ANTI:')) {
      continue
    } // Removed field
    if (line.startsWith('WORKFLOW:')) {
      prettified.push(
        `Workflow: ${line.slice(9).trim().replaceAll('|', ' \u00b7 ')}`,
      )
      continue
    }
    if (line.startsWith('CONSTRAINTS')) {
      continue
    } // Removed field
    if (line.startsWith('DONE_WHEN')) {
      const [, content = ''] = line.split(':', 2)
      prettified.push(`Done when: ${content.replaceAll(' | ', '; ').trim()}`)
      continue
    }
    if (line.startsWith('COMPLETE_READY:')) {
      prettified.push(
        `Ready gates: ${line.slice(15).trim().replaceAll('|', ' \u00b7 ')}`,
      )
      continue
    }
    if (line.startsWith('SYNC_SKIPS:')) {
      prettified.push(`Sync skips: ${line.slice(11).trim()}`)
      continue
    }
    if (line.startsWith('LANE:')) {
      prettified.push(
        `Lane: ${line.slice(5).trim().replaceAll('|', ' \u00b7 ')}`,
      )
      continue
    }
    if (line.startsWith('SPECIALISTS:')) {
      prettified.push(
        `Specialists: ${line.slice(12).trim().replaceAll('|', ' \u00b7 ')}`,
      )
      continue
    }
    if (line.startsWith('DECISIONS[')) {
      continue
    } // Removed field
    if (/^d\d+:/i.test(line)) {
      continue
    } // Removed field (decision items)
    if (line.startsWith('SUBTASKS[')) {
      const [, content = ''] = line.split(':', 2)
      prettified.push(`Subtasks: ${content.trim()}`)
      continue
    }
    if (/^\d+(\.\d+)?\s+_+/.test(line)) {
      prettified.push(line.replace(/_+/g, '').replace(/\s+/g, ' ').trim())
      continue
    }
    prettified.push(line)
  }
  return prettified.join('\n')
}

export function prettifyDisplayText(value: string): string {
  const extracted = extractWrappedTextPayload(value)
  const base = extracted ?? value
  // Strip observability tags — shown separately in narration timeline
  const stripped = base
    .replace(/\[\[P:[a-z_]+(?::[^\]]*?)?\]?\]?/g, '')
    .replace(/\s*(?:Applied:\s*)?\[(?:M|G|R):[a-f0-9]{3,8}[^\]]*\]?/g, '')
    .replace(/\[\[F:[^\]]*\]?\]?/g, '')
    .replace(/\[\[S:[^\]]*\]?\]?/g, '')
    .replace(/\n{3,}/g, '\n\n')
  return humanizeTaskContextText(unescapeDisplayText(stripped).trim())
}

export function addUniqueText(
  target: string[],
  seen: Set<string>,
  value: string | null | undefined,
): void {
  if (!value) return
  const trimmed = value.trim()
  if (!trimmed) return
  const normalized = normalizeText(trimmed)
  if (seen.has(normalized)) return
  seen.add(normalized)
  target.push(trimmed)
}
