import { describe, expect, it } from 'vitest'

import { handleStreamEvent } from '../../../packages/chat-ui/src/hooks/chat-stream/message-handlers'
import type { StreamState } from '../../../packages/chat-ui/src/hooks/chat-stream/types'
import type {
  ChatMessage,
  StreamMessage,
} from '../../../packages/chat-ui/src/types/chat'

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
  return { state, message: messages[0] }
}

describe('turn_retry', () => {
  it('drops only the interrupted turn: text and tools after the last tool result', () => {
    const { state, message } = replay([
      { type: 'content', content: 'Reading. ' },
      {
        type: 'tool_use',
        tool_id: 't1',
        tool_name: 'read_file',
        tool_input: {},
      },
      { type: 'tool_result', tool_id: 't1', tool_result: 'ok' },
      { type: 'content', content: 'Half a sent' },
      {
        type: 'tool_use',
        tool_id: 't2',
        tool_name: 'edit_file',
        tool_input: {},
      },
      { type: 'turn_retry', attempt: 1, max_retries: 2, reason: 'stalled' },
    ])
    expect(state.content).toBe('Reading. ')
    expect(state.tools.map((t) => t.id)).toEqual(['t1'])
    expect(message.content).toBe('Reading. ')
    expect(message.statusLabel).toBe('Retrying (1/2)')
  })

  it('clears everything when the first turn is retried', () => {
    const { state } = replay([
      { type: 'thinking', content: 'hmm' },
      { type: 'content', content: 'partial' },
      { type: 'turn_retry', attempt: 1, max_retries: 2, reason: 'stalled' },
      { type: 'content', content: 'fresh' },
    ])
    expect(state.content).toBe('fresh')
    expect(state.thinking).toBe('')
  })
})
