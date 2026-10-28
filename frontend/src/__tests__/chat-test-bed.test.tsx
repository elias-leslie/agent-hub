import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { MessageRuntimeDetails } from '../../../packages/chat-ui/src/components/MessageRuntimeDetails'
import { handleStreamEvent } from '../../../packages/chat-ui/src/hooks/chat-stream/message-handlers'
import type { StreamState } from '../../../packages/chat-ui/src/hooks/chat-stream/types'
import type {
  ChatMessage,
  StreamMessage,
} from '../../../packages/chat-ui/src/types/chat'

const mocks = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('@/lib/agent-hub-client', () => ({
  agentHubClient: { sessions: { list: mocks.list } },
}))

import { ChatSessions } from '@/app/chat/components/ChatSessions'

function replay(events: StreamMessage[]) {
  const state: StreamState = {
    content: '',
    thinking: '',
    tools: [],
    lastSeq: 0,
  }
  let messages = [{ id: 'a', role: 'assistant', content: '' } as ChatMessage]
  const setMessages = ((update: (prev: ChatMessage[]) => ChatMessage[]) => {
    messages = update(messages)
  }) as React.Dispatch<React.SetStateAction<ChatMessage[]>>
  for (const event of events)
    handleStreamEvent(event, 'a', state, setMessages, () => {})
  return messages[0]
}

describe('requested and served model', () => {
  it('records the model asked for, the one that answered, the fallback and each retry', () => {
    const message = replay([
      { type: 'connected', model: 'claude-opus-5-5', session_id: 's' },
      { type: 'turn_retry', attempt: 1, max_retries: 2, reason: 'stalled' },
      {
        type: 'content',
        content: 'Hi',
        model: 'claude-opus-5-5',
        model_used: 'gpt-5.5',
        agent_used: 'chat',
        fallback_used: true,
        fallback_reason: 'usage_limit',
      },
      { type: 'done', model: 'claude-opus-5-5', model_used: 'gpt-5.5' },
    ])
    expect(message.requestedModel).toBe('claude-opus-5-5')
    expect(message.servedModel).toBe('gpt-5.5')
    expect(message.fallbackUsed).toBe(true)
    expect(message.agentName).toBe('chat')
    expect(message.retries).toEqual([{ attempt: 1, max: 2, reason: 'stalled' }])
  })

  it('shows "requested X, answered by Y", the fallback badge and the retry marker', () => {
    render(
      <MessageRuntimeDetails
        message={{
          id: 'a',
          role: 'assistant',
          content: 'Hi',
          timestamp: new Date(),
          requestedModel: 'claude-opus-5-5',
          servedModel: 'gpt-5.5',
          fallbackUsed: true,
          fallbackReason: 'usage_limit',
          retries: [{ attempt: 1, max: 2, reason: 'stalled' }],
        }}
      />,
    )
    expect(screen.getByTestId('message-route')).toHaveTextContent(
      'requested claude-opus-5-5, answered by gpt-5.5',
    )
    expect(screen.getByText(/fallback: usage_limit/)).toBeInTheDocument()
    expect(screen.getByText(/retried 1\/2: stalled/)).toBeInTheDocument()
  })

  it('names only the model that answered when it is the one asked for', () => {
    render(
      <MessageRuntimeDetails
        message={{
          id: 'a',
          role: 'assistant',
          content: 'Hi',
          timestamp: new Date(),
          requestedModel: 'gpt-5.5',
          servedModel: 'gpt-5.5',
        }}
      />,
    )
    expect(screen.getByTestId('message-route')).toHaveTextContent(
      /^answered by gpt-5\.5$/,
    )
    expect(screen.queryByText(/fallback/)).toBeNull()
  })
})

describe('ChatSessions', () => {
  it('marks sessions with a running turn and says when the list failed', async () => {
    mocks.list.mockResolvedValueOnce({
      total: 2,
      sessions: [
        {
          id: 'aaaaaaaa-1',
          title: 'Audit the cache',
          agent_slug: 'coder',
          turn_state: 'running',
          turn_phase: 'running_tool:read_file',
          updated_at: new Date().toISOString(),
        },
        {
          id: 'bbbbbbbb-2',
          title: 'Older chat',
          agent_slug: 'chat',
          turn_state: 'idle',
          updated_at: new Date().toISOString(),
        },
      ],
    })
    render(<ChatSessions activeSessionId={null} onSelect={() => {}} />)
    await waitFor(() =>
      expect(screen.getByText('Audit the cache')).toBeInTheDocument(),
    )
    expect(screen.getByText('Running read_file')).toBeVisible()
    expect(screen.getByText(/1 running/)).toBeVisible()
  })

  it('shows a failed load as failed, not as empty', async () => {
    mocks.list.mockRejectedValueOnce(new Error('403'))
    render(<ChatSessions activeSessionId={null} onSelect={() => {}} />)
    expect(
      await screen.findByText('Could not load sessions: 403'),
    ).toBeVisible()
    expect(screen.queryByText('No chat sessions yet.')).toBeNull()
  })
})
