import { afterEach, describe, expect, it, vi } from 'vitest'

import { processStreamWithReconnect } from '../../../packages/chat-ui/src/hooks/chat-stream/stream-processor'

function sseResponse(lines: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(`${lines.join('\n')}\n`))
      controller.close()
    },
  })
  return new Response(body, { status: 200 })
}

function brokenResponse(): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        new TextEncoder().encode(
          'data: {"type":"content","content":"Hi","seq":1}\n',
        ),
      )
      controller.error(new TypeError('network error'))
    },
  })
  return new Response(body, { status: 200 })
}

function run() {
  return processStreamWithReconnect(
    'agent',
    'assistant-1',
    new AbortController(),
    { agent_slug: 'agent', messages: [], stream: true } as never,
    { content: '', thinking: '', tools: [], lastSeq: 0 },
    vi.fn(),
    vi.fn(),
    vi.fn(),
    {},
    '/api/complete',
  )
}

describe('processStreamWithReconnect', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('surfaces backend error events instead of swallowing them', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        sseResponse([
          'data: {"type":"error","error":"quota exhausted","seq":1}',
        ]),
      )
    vi.stubGlobal('fetch', fetchMock)

    await expect(run()).rejects.toThrow('quota exhausted')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not re-POST the completion after the stream has started', async () => {
    const fetchMock = vi.fn().mockResolvedValue(brokenResponse())
    vi.stubGlobal('fetch', fetchMock)

    await expect(run()).rejects.toThrow('network error')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
