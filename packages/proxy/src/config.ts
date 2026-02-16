import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export interface ProxyConfig {
  agentHubUrl: string
  clientId: string
  clientSecret: string
  requestSource: string
  streamTimeout: number
}

export interface ProxyOptions {
  /** Agent Hub backend URL. Default: process.env.AGENT_HUB_URL || 'http://localhost:8003' */
  agentHubUrl?: string
  /** Override client ID (skips env lookup). */
  clientId?: string
  /** Override client secret (skips env lookup). */
  clientSecret?: string
  /** Override request source (skips env lookup). */
  requestSource?: string
  /** Env variable prefix. E.g. 'SUMMITFLOW' reads SUMMITFLOW_CLIENT_ID. */
  envPrefix?: string
  /** SSE/WebSocket timeout in ms. Default: 300_000 (5 min). */
  streamTimeout?: number
  /** Fall back to ~/.env.local when process.env doesn't have the key. */
  readEnvLocal?: boolean
}

let envLocalCache: Record<string, string> | null = null

function loadEnvLocal(): Record<string, string> {
  if (envLocalCache !== null) return envLocalCache
  try {
    const content = readFileSync(join(homedir(), '.env.local'), 'utf-8')
    const entries: Record<string, string> = {}
    for (const line of content.split('\n')) {
      const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/)
      if (match) entries[match[1]] = match[2].trim()
    }
    envLocalCache = entries
    return entries
  } catch {
    envLocalCache = {}
    return {}
  }
}

function readEnv(key: string, useEnvLocal: boolean): string {
  return process.env[key] || (useEnvLocal ? loadEnvLocal()[key] : undefined) || ''
}

/**
 * Resolve proxy configuration from explicit values, environment variables,
 * and optionally ~/.env.local.
 *
 * Lookup order: explicit option > process.env > ~/.env.local (if readEnvLocal) > default.
 */
export function resolveConfig(options?: ProxyOptions): ProxyConfig {
  const prefix = options?.envPrefix || ''
  const useLocal = options?.readEnvLocal ?? false
  const envKey = (key: string) => (prefix ? `${prefix}_${key}` : key)

  return {
    agentHubUrl:
      options?.agentHubUrl || readEnv('AGENT_HUB_URL', useLocal) || 'http://localhost:8003',
    clientId: options?.clientId || readEnv(envKey('CLIENT_ID'), useLocal),
    clientSecret: options?.clientSecret || readEnv(envKey('CLIENT_SECRET'), useLocal),
    requestSource: options?.requestSource || readEnv(envKey('REQUEST_SOURCE'), useLocal),
    streamTimeout: options?.streamTimeout ?? 300_000,
  }
}
