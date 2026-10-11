export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

import { buildInternalHeaders, getApiBaseUrl } from '@/lib/api-config'
import { requireOwner } from '@/lib/proxy-identity'

const BACKEND_URL = `${getApiBaseUrl()}/api/memory/capture/stream`

export async function GET(request: Request): Promise<Response> {
  const denied = await requireOwner(request)
  if (denied) return denied
  const headers: Record<string, string> = {
    Accept: 'text/event-stream',
    ...buildInternalHeaders(),
  }

  const upstream = await fetch(BACKEND_URL, {
    headers,
    cache: 'no-store',
  })

  if (!upstream.ok || !upstream.body) {
    return new Response('SSE upstream unavailable', { status: 502 })
  }

  return new Response(upstream.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  })
}
