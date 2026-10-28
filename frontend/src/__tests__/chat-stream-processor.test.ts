import { createClient } from '@agent-hub/sdk'
import { describe, expect, it, vi } from 'vitest'

import {
  attachToTurn,
  processStream,
} from '../../../packages/chat-ui/src/hooks/chat-stream/stream-processor'
import type { StreamState } from '../../../packages/chat-ui/src/hooks/chat-stream/types'

function sse(events: object[]): Response {
  const text = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('')
  return new Response(text, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

/** Delivers the events, then drops the connection. */
function broken(events: object[]): Response {
  const text = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('')
  let sent = false
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (!sent) {
        sent = true
        controller.enqueue(new TextEncoder().encode(text))
        return
      }
      controller.error(new TypeError('network error'))
    },
  })
  return new Response(body, { status: 200 })
}

function harness(fetchMock: ReturnType<typeof vi.fn>) {
  const client = createClient({
    baseUrl: 'http://hub.test',
    fetch: fetchMock as never,
  })
  const state: StreamState = {
    content: '',
    thinking: '',
    tools: [],
    lastSeq: 0,
  }
  const sink = {
    assistantId: 'assistant-1',
    streamState: state,
    setMessages: vi.fn(),
    setCurrentSessionId: vi.fn(),
    setStatus: vi.fn(),
    setTurnPhase: vi.fn(),
  }
  return { client, state, sink }
}

const request = { agent_slug: 'agent', messages: [], project_id: 'p' } as never

describe('processStream', () => {
  it('surfaces backend error events instead of swallowing them', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        sse([{ type: 'error', error: 'quota exhausted', seq: 1 }]),
      )
    const { client, sink } = harness(fetchMock)

    await expect(
      processStream(client, request, sink, new AbortController().signal),
    ).rejects.toThrow('quota exhausted')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('follows the running turn after the connection drops instead of re-POSTing the completion', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        broken([
          { type: 'connected', seq: 1, session_id: 's1', turn_id: 't1' },
          { type: 'content', seq: 2, content: 'Hel' },
        ]),
      )
      .mockResolvedValueOnce(
        sse([
          { type: 'content', seq: 2, content: 'Hel' },
          { type: 'content', seq: 3, content: 'lo' },
          { type: 'done', seq: 4, session_id: 's1' },
        ]),
      )
    const { client, state, sink } = harness(fetchMock)

    const outcome = await processStream(
      client,
      request,
      sink,
      new AbortController().signal,
    )

    expect(outcome).toBe('finished')
    expect(state.content).toBe('Hello')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[0][1].method).toBe('POST')
    expect(fetchMock.mock.calls[1][0]).toContain(
      '/api/sessions/s1/stream?after_seq=2',
    )
    expect(sink.setStatus).toHaveBeenCalledWith('reconnecting')
    expect(sink.setStatus).toHaveBeenLastCalledWith('streaming')
    expect(sink.setTurnPhase).toHaveBeenLastCalledWith(null)
  })

  it('reports a cancelled turn', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sse([
        { type: 'connected', seq: 1, session_id: 's1' },
        { type: 'cancel_acknowledged', seq: 2, session_id: 's1' },
      ]),
    )
    const { client, sink } = harness(fetchMock)

    expect(
      await processStream(client, request, sink, new AbortController().signal),
    ).toBe('cancelled')
  })
})

describe('attachToTurn', () => {
  it('replays a running turn from the start and tracks its phase', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sse([
        { type: 'thinking', seq: 1, content: 'hm' },
        {
          type: 'tool_use',
          seq: 2,
          tool_id: 't',
          tool_name: 'bash',
          tool_input: {},
        },
        {
          type: 'tool_result',
          seq: 3,
          tool_id: 't',
          tool_result: 'ok',
          tool_status: 'complete',
        },
        { type: 'content', seq: 4, content: 'done it' },
        { type: 'done', seq: 5, session_id: 's1' },
      ]),
    )
    const { client, state, sink } = harness(fetchMock)

    const outcome = await attachToTurn(
      client,
      's1',
      sink,
      new AbortController().signal,
    )

    expect(outcome).toBe('finished')
    expect(fetchMock.mock.calls[0][0]).toContain(
      '/api/sessions/s1/stream?after_seq=0',
    )
    expect(state.content).toBe('done it')
    expect(sink.setTurnPhase.mock.calls.map((c) => c[0])).toEqual([
      'thinking',
      'running_tool:bash',
      'waiting_for_model',
      'responding',
      null,
      null,
    ])
  })

  it('returns idle when no turn is running', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        sse([{ type: 'idle', session_id: 's1', last_state: 'completed' }]),
      )
    const { client, sink } = harness(fetchMock)

    expect(
      await attachToTurn(client, 's1', sink, new AbortController().signal),
    ).toBe('idle')
  })
})
