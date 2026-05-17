/**
 * Agent Hub auth proxy Route Handler.
 *
 * Lives at /api/proxy/[...path] and injects X-Client-Id and X-Request-Source
 * headers before forwarding to the Agent Hub API backend. This is needed
 * because Next.js rewrites can't inject custom headers.
 *
 * The AH frontend's next.config.ts routes /api/* through this handler
 * instead of directly to the backend.
 */

import { buildInternalHeaders, getApiBaseUrl } from '@/lib/api-config'

const SSE_HEADERS: Record<string, string> = {
  'Cache-Control': 'no-cache, no-transform',
  'X-Accel-Buffering': 'no',
  Connection: 'keep-alive',
}
const DASHBOARD_ONLY_PREFIXES = new Set(['runtime-context'])
const DASHBOARD_CLIENT_ID =
  process.env.AGENT_HUB_DASHBOARD_CLIENT_ID?.trim() ||
  process.env.NEXT_PUBLIC_AGENT_HUB_DASHBOARD_CLIENT_ID?.trim() ||
  'agent-hub-dashboard'
const DASHBOARD_CLIENT_IDS = new Set([
  DASHBOARD_CLIENT_ID,
  'agent-hub-dashboard',
])
const DASHBOARD_REQUEST_SOURCE =
  process.env.AGENT_HUB_DASHBOARD_REQUEST_SOURCE?.trim() ||
  'agent-hub-dashboard'
const DASHBOARD_REQUEST_SOURCES = new Set([
  DASHBOARD_REQUEST_SOURCE,
  'agent-hub-dashboard',
])

function buildUpstreamUrl(path: string[], searchParams?: string): string {
  const joined = path.join('/')
  const qs = searchParams ? `?${searchParams}` : ''
  return `${getApiBaseUrl()}/api/${joined}${qs}`
}

type RouteContext = { params: Promise<{ path: string[] }> }

const auth = buildInternalHeaders()

function dashboardProxyGuard(
  request: Request,
  path: string[],
): Response | null {
  if (!DASHBOARD_ONLY_PREFIXES.has(path[0] ?? '')) return null

  const clientId = request.headers.get('X-Client-Id')?.trim()
  const requestSource = request.headers.get('X-Request-Source')?.trim()
  if (
    clientId &&
    DASHBOARD_CLIENT_IDS.has(clientId) &&
    requestSource &&
    DASHBOARD_REQUEST_SOURCES.has(requestSource)
  ) {
    return null
  }

  return Response.json(
    {
      error: 'dashboard_only',
      message: 'This API route is only available to the Agent Hub dashboard.',
    },
    { status: 401 },
  )
}

export async function GET(request: Request, { params }: RouteContext) {
  const { path } = await params
  const guard = dashboardProxyGuard(request, path)
  if (guard) return guard
  const url = buildUpstreamUrl(
    path,
    new URL(request.url).searchParams.toString(),
  )
  const response = await fetch(url, { headers: auth })
  return new Response(response.body, {
    status: response.status,
    headers: {
      'Content-Type':
        response.headers.get('Content-Type') ?? 'application/json',
    },
  })
}

export async function POST(request: Request, { params }: RouteContext) {
  const { path } = await params
  const guard = dashboardProxyGuard(request, path)
  if (guard) return guard
  const url = buildUpstreamUrl(path)
  const body = await request.text()
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...auth },
    body,
  })
  const contentType = response.headers.get('Content-Type') ?? 'application/json'
  const isSSE = contentType.includes('text/event-stream')
  return new Response(response.body, {
    status: response.status,
    headers: {
      'Content-Type': contentType,
      ...(isSSE ? SSE_HEADERS : {}),
    },
  })
}

export async function PUT(request: Request, { params }: RouteContext) {
  const { path } = await params
  const guard = dashboardProxyGuard(request, path)
  if (guard) return guard
  const url = buildUpstreamUrl(path)
  const body = await request.text()
  const response = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...auth },
    body,
  })
  return new Response(response.body, {
    status: response.status,
    headers: {
      'Content-Type':
        response.headers.get('Content-Type') ?? 'application/json',
    },
  })
}

export async function PATCH(request: Request, { params }: RouteContext) {
  const { path } = await params
  const guard = dashboardProxyGuard(request, path)
  if (guard) return guard
  const url = buildUpstreamUrl(path)
  const body = await request.text()
  const response = await fetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...auth },
    body,
  })
  return new Response(response.body, {
    status: response.status,
    headers: {
      'Content-Type':
        response.headers.get('Content-Type') ?? 'application/json',
    },
  })
}

export async function DELETE(request: Request, { params }: RouteContext) {
  const { path } = await params
  const guard = dashboardProxyGuard(request, path)
  if (guard) return guard
  const url = buildUpstreamUrl(
    path,
    new URL(request.url).searchParams.toString(),
  )
  const body = await request.text()
  const response = await fetch(url, {
    method: 'DELETE',
    headers: body ? { 'Content-Type': 'application/json', ...auth } : auth,
    ...(body ? { body } : {}),
  })
  return new Response(response.body, {
    status: response.status,
    headers: {
      'Content-Type':
        response.headers.get('Content-Type') ?? 'application/json',
    },
  })
}
