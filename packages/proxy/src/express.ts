import type { ServerResponse } from 'node:http'
import { createProxyMiddleware } from 'http-proxy-middleware'
import { resolveConfig, type ProxyOptions } from './config'
import { buildAuthHeaders } from './headers'

/**
 * Create Express middleware that proxies to Agent Hub with client credentials.
 *
 * Returns an http-proxy-middleware instance with WebSocket support.
 * The returned middleware has an `.upgrade` property for WebSocket handling.
 *
 * Usage:
 * ```ts
 * import { createExpressProxy } from '@agent-hub/proxy/express'
 *
 * const proxy = createExpressProxy({
 *   envPrefix: 'MONKEY_FIGHT',
 *   readEnvLocal: true,
 * })
 * app.use('/agent-hub', proxy)
 * server.on('upgrade', proxy.upgrade)
 * ```
 */
export function createExpressProxy(options?: ProxyOptions & { stripPrefix?: string }) {
  const config = resolveConfig(options)
  const auth = buildAuthHeaders(config)
  const prefix = options?.stripPrefix ?? '/agent-hub'
  const prefixRegex = new RegExp(`^${prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`)

  return createProxyMiddleware({
    target: config.agentHubUrl,
    changeOrigin: true,
    ws: true,
    timeout: config.streamTimeout,
    proxyTimeout: config.streamTimeout,
    pathRewrite: (path) => path.replace(prefixRegex, ''),
    on: {
      proxyReq: (proxyReq) => {
        for (const [key, value] of Object.entries(auth)) {
          proxyReq.setHeader(key, value)
        }
      },
      error: (err, _req, res) => {
        console.error(`Agent Hub proxy error: ${err.message}`)
        // res is a Socket for WebSocket upgrades, not an HTTP response
        if ('writeHead' in res) {
          ;(res as ServerResponse).writeHead(502, { 'Content-Type': 'application/json' })
          ;(res as ServerResponse).end(JSON.stringify({ error: 'Agent Hub unavailable' }))
        }
      },
    },
  })
}
