/**
 * Utility functions for Memory API operations.
 */

import { fetchApi } from './api-config'
import type { MemoryEpisode } from './memory-types'

// Build headers with optional group ID
export function buildHeaders(
  groupId?: string,
  contentType?: string,
): HeadersInit {
  const headers: HeadersInit = {}
  if (groupId) headers['x-group-id'] = groupId
  if (contentType) headers['Content-Type'] = contentType
  return headers
}

// Generic fetch wrapper with error handling
export async function apiFetch<T>(
  url: string,
  options: RequestInit = {},
  errorPrefix = 'API request failed',
): Promise<T> {
  const response = await fetchApi(url, options)
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || `${errorPrefix}: ${response.status}`)
  }
  return response.json()
}

// Export memories as JSON blob
export function exportMemoriesAsJson(episodes: MemoryEpisode[]): Blob {
  const data = {
    exported_at: new Date().toISOString(),
    count: episodes.length,
    episodes,
  }
  return new Blob([JSON.stringify(data, null, 2)], {
    type: 'application/json',
  })
}

// Trigger download of JSON blob
export function downloadJson(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
