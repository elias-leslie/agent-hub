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

function buildUpstreamUrl(path: string[], searchParams?: string): string {
  const joined = path.join('/')
  const qs = searchParams ? `?${searchParams}` : ''
  return `${getApiBaseUrl()}/api/${joined}${qs}`
}

type RouteContext = { params: Promise<{ path: string[] }> }

const auth = buildInternalHeaders()

export async function GET(request: Request, { params }: RouteContext) {
  const { path } = await params
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
