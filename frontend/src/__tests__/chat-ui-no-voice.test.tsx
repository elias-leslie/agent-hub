import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { createQueryClientWrapper } from './test-utils'

// A host without passport-client: loading it must fail loudly, and the chat must not notice.
vi.mock('@agent-hub/passport-client', () => {
  throw new Error('@agent-hub/passport-client must not load with the chat')
})

const here = dirname(fileURLToPath(import.meta.url))
const chatUiSrc = resolve(here, '../../../packages/chat-ui/src')

describe('@agent-hub/chat-ui without voice', () => {
  it('renders the panel, with no mic or speaker, when passport-client is unavailable', async () => {
    const { ChatPanel } = await import('@agent-hub/chat-ui')
    const client = {
      turns: { stream: vi.fn(), attach: vi.fn(), cancel: vi.fn() },
      sessions: { get: vi.fn(), fork: vi.fn() },
      models: { list: vi.fn().mockResolvedValue([]) },
    }

    render(<ChatPanel agentSlug="chat" client={client as never} />, {
      wrapper: createQueryClientWrapper(),
    })

    expect(screen.getByTestId('chat-input')).toBeInTheDocument()
    expect(screen.queryByTestId('mic-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('speaker-button')).not.toBeInTheDocument()
  })

  it('shows the mic and speaker when a host passes voice', async () => {
    const { ChatPanel } = await import('@agent-hub/chat-ui')
    const client = {
      turns: { stream: vi.fn(), attach: vi.fn(), cancel: vi.fn() },
      sessions: { get: vi.fn(), fork: vi.fn() },
      models: { list: vi.fn().mockResolvedValue([]) },
    }
    const setTranscriptHandler = vi.fn()
    const voice = {
      micAvailable: true,
      speakerAvailable: true,
      isRecording: false,
      isSpeaking: false,
      ttsEnabled: false,
      selectedVoice: 'v',
      startRecording: vi.fn(),
      stopRecording: vi.fn(),
      speakText: vi.fn().mockResolvedValue(undefined),
      stopSpeaking: vi.fn(),
      setTtsEnabled: vi.fn(),
      setTranscriptHandler,
    }

    render(
      <ChatPanel agentSlug="chat" client={client as never} voice={voice} />,
      { wrapper: createQueryClientWrapper() },
    )

    expect(screen.getByTestId('mic-button')).toBeInTheDocument()
    expect(screen.getByTestId('speaker-button')).toBeInTheDocument()
    expect(setTranscriptHandler).toHaveBeenCalledWith(expect.any(Function))
  })

  it('reaches no passport-client import from the main entry point', () => {
    const seen = new Set<string>()
    const offenders: string[] = []
    const visit = (file: string) => {
      if (seen.has(file)) return
      seen.add(file)
      const source = readFileSync(file, 'utf8')
      for (const match of source.matchAll(
        /(?:import|export)[^'"]*?from\s+['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)/g,
      )) {
        const target = match[1] ?? match[2]
        if (target.includes('passport-client')) offenders.push(file)
        if (target.startsWith('.')) {
          const base = resolve(dirname(file), target)
          for (const candidate of [
            `${base}.ts`,
            `${base}.tsx`,
            `${base}/index.ts`,
          ]) {
            try {
              readFileSync(candidate)
              visit(candidate)
              break
            } catch {
              // not this extension
            }
          }
        }
      }
    }
    visit(resolve(chatUiSrc, 'index.ts'))

    expect(seen.size).toBeGreaterThan(20)
    expect(offenders).toEqual([])
    // The voice entry is where passport-client lives.
    expect(
      readFileSync(resolve(chatUiSrc, 'voice/use-chat-voice.ts'), 'utf8'),
    ).toContain('@agent-hub/passport-client')
  })
})
