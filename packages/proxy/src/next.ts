import { resolveConfig, type ProxyOptions } from './config'
import { buildAuthHeaders, buildUpstreamUrl, SSE_HEADERS } from './headers'

type RouteContext = { params: Promise<{ path: string[] }> }
type RouteHandler = (request: Request, context: RouteContext) => Promise<Response>

/**
 * Create Next.js App Router Route Handlers for Agent Hub proxy.
 *
 * Returns { GET, POST, PUT, DELETE } handlers that proxy to Agent Hub
 * with client credentials injected server-side.
 *
 * Usage in app/proxy-hub/agent-hub/[...path]/route.ts:
 * ```ts
 * import { createRouteHandlers } from '@agent-hub/proxy/next'
 * export const { GET, POST, PUT, DELETE } = createRouteHandlers({
 *   envPrefix: 'SUMMITFLOW',
 * })
 * ```
 */
export function createRouteHandlers(options?: ProxyOptions): {
  GET: RouteHandler
  POST: RouteHandler
  PUT: RouteHandler
  DELETE: RouteHandler
} {
  const config = resolveConfig(options)
  const auth = buildAuthHeaders(config)

  const GET: RouteHandler = async (request, { params }) => {
    const { path } = await params
    const url = buildUpstreamUrl(config, path, new URL(request.url).searchParams.toString())
    const response = await fetch(url, { headers: auth })
    return new Response(response.body, {
      status: response.status,
      headers: {
        'Content-Type': response.headers.get('Content-Type') || 'application/json',
      },
    })
  }

  const POST: RouteHandler = async (request, { params }) => {
    const { path } = await params
    const url = buildUpstreamUrl(config, path)
    const body = await request.text()
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...auth },
      body,
    })
    const contentType = response.headers.get('Content-Type') || 'application/json'
    const isSSE = contentType.includes('text/event-stream')
    return new Response(response.body, {
      status: response.status,
      headers: {
        'Content-Type': contentType,
        ...(isSSE ? SSE_HEADERS : {}),
      },
    })
  }

  const PUT: RouteHandler = async (request, { params }) => {
    const { path } = await params
    const url = buildUpstreamUrl(config, path)
    const body = await request.text()
    const response = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...auth },
      body,
    })
    return new Response(response.body, {
      status: response.status,
      headers: {
        'Content-Type': response.headers.get('Content-Type') || 'application/json',
      },
    })
  }

  const DELETE: RouteHandler = async (request, { params }) => {
    const { path } = await params
    const url = buildUpstreamUrl(config, path, new URL(request.url).searchParams.toString())
    const response = await fetch(url, {
      method: 'DELETE',
      headers: auth,
    })
    return new Response(response.body, {
      status: response.status,
      headers: {
        'Content-Type': response.headers.get('Content-Type') || 'application/json',
      },
    })
  }

  return { GET, POST, PUT, DELETE }
}
