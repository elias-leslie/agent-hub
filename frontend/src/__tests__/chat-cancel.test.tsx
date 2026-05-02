/**
 * Tests for chat cancellation UI.
 */

import { type ChatMessage, MessageInput, MessageList } from '@agent-hub/chat-ui'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createQueryClientWrapper } from './test-utils'

describe('MessageInput', () => {
  const mockOnSend = vi.fn()
  const mockOnCancel = vi.fn()

  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('shows Send button when idle', () => {
    render(
      <MessageInput
        onSend={mockOnSend}
        onCancel={mockOnCancel}
        status="idle"
      />,
      { wrapper: createQueryClientWrapper() },
    )

    expect(screen.getByLabelText('Send message')).toBeInTheDocument()
    expect(screen.queryByLabelText('Stop generating')).not.toBeInTheDocument()
  })

  it('shows Stop button when streaming', () => {
    render(
      <MessageInput
        onSend={mockOnSend}
        onCancel={mockOnCancel}
        status="streaming"
      />,
      { wrapper: createQueryClientWrapper() },
    )

    expect(screen.getByLabelText('Stop generating')).toBeInTheDocument()
    expect(screen.queryByLabelText('Send message')).not.toBeInTheDocument()
  })

  it('shows Stop button when cancelling', () => {
    render(
      <MessageInput
        onSend={mockOnSend}
        onCancel={mockOnCancel}
        status="cancelling"
      />,
      { wrapper: createQueryClientWrapper() },
    )

    expect(screen.getByLabelText('Stop generating')).toBeInTheDocument()
  })

  it('calls onCancel when Stop button is clicked', () => {
    render(
      <MessageInput
        onSend={mockOnSend}
        onCancel={mockOnCancel}
        status="streaming"
      />,
      { wrapper: createQueryClientWrapper() },
    )

    fireEvent.click(screen.getByLabelText('Stop generating'))
    expect(mockOnCancel).toHaveBeenCalledTimes(1)
  })

  it('disables Stop button when cancelling', () => {
    render(
      <MessageInput
        onSend={mockOnSend}
        onCancel={mockOnCancel}
        status="cancelling"
      />,
      { wrapper: createQueryClientWrapper() },
    )

    const stopButton = screen.getByLabelText('Stop generating')
    expect(stopButton).toBeDisabled()
  })

  it('disables textarea when streaming', () => {
    render(
      <MessageInput
        onSend={mockOnSend}
        onCancel={mockOnCancel}
        status="streaming"
      />,
      { wrapper: createQueryClientWrapper() },
    )

    const textarea = screen.getByPlaceholderText('Waiting for response...')
    expect(textarea).toBeDisabled()
  })
})

describe('MessageList', () => {
  it('shows cancelled indicator on cancelled messages', () => {
    const messages: ChatMessage[] = [
      {
        id: '1',
        role: 'user',
        content: 'Hello',
        timestamp: new Date(),
      },
      {
        id: '2',
        role: 'assistant',
        content: 'Hi there! I was just starting to explain—',
        timestamp: new Date(),
        cancelled: true,
        inputTokens: 10,
        outputTokens: 15,
      },
    ]

    render(<MessageList messages={messages} isStreaming={false} />)

    expect(screen.getByText('[cancelled]')).toBeInTheDocument()
  })

  it('shows token counts on completed messages', () => {
    const messages: ChatMessage[] = [
      {
        id: '1',
        role: 'assistant',
        content: 'Hello!',
        timestamp: new Date(),
        inputTokens: 100,
        outputTokens: 50,
      },
    ]

    render(<MessageList messages={messages} isStreaming={false} />)

    expect(screen.getByText(/In: 100/)).toBeInTheDocument()
    expect(screen.getByText(/Out: 50/)).toBeInTheDocument()
  })

  it('shows empty state when no messages', () => {
    render(<MessageList messages={[]} isStreaming={false} />)

    expect(screen.getByText('Start a conversation')).toBeInTheDocument()
  })
})
