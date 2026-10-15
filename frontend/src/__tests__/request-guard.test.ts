import { describe, expect, it } from 'vitest'
import { allowedOrigins, refusal } from '@/lib/request-guard.mjs'

const origins = allowedOrigins(3003, {})
const post = (headers: Record<string, string>) =>
  refusal(
    { method: 'POST', headers: { host: 'localhost:3003', ...headers } },
    origins,
  )

describe('frontend request guard', () => {
  it('refuses a cross-site write such as a no-preflight text/plain POST', () => {
    expect(
      post({ origin: 'https://evil.example', 'content-type': 'text/plain' }),
    ).toEqual({
      status: 403,
      error: 'origin_not_allowed',
    })
    expect(post({ origin: 'null' })?.status).toBe(403)
    expect(post({ 'sec-fetch-site': 'cross-site' })?.status).toBe(403)
    expect(post({ 'sec-fetch-site': 'same-site' })?.status).toBe(403)
  })

  it('lets our own pages and originless clients write', () => {
    expect(post({ origin: 'http://localhost:3003' })).toBeNull()
    expect(post({ origin: 'http://127.0.0.1:3003' })).toBeNull()
    expect(post({ 'sec-fetch-site': 'same-origin' })).toBeNull()
    expect(post({})).toBeNull()
    expect(
      refusal(
        {
          method: 'PATCH',
          headers: {
            host: 'agent.summitflow.dev',
            origin: 'https://agent.summitflow.dev',
          },
        },
        origins,
      ),
    ).toBeNull()
  })

  it('does not block cross-site reads (CORS keeps them unreadable)', () => {
    expect(
      refusal(
        {
          method: 'GET',
          headers: { host: 'localhost:3003', origin: 'https://evil.example' },
        },
        origins,
      ),
    ).toBeNull()
  })

  it('checks Origin on WebSocket upgrades', () => {
    const headers = { host: 'localhost:3003', origin: 'https://evil.example' }
    expect(
      refusal({ method: 'GET', headers, upgrade: true }, origins)?.status,
    ).toBe(403)
  })

  it('refuses a foreign Host (DNS rebinding) even for reads', () => {
    for (const host of [
      'evil.example',
      'evil.example:3003',
      'localhost.evil.example',
      '',
    ]) {
      expect(refusal({ method: 'GET', headers: { host } }, origins)).toEqual({
        status: 400,
        error: 'host_not_allowed',
      })
    }
    for (const host of [
      'localhost:3003',
      '127.0.0.1',
      '[::1]:3003',
      'agent.summitflow.dev',
    ]) {
      expect(refusal({ method: 'GET', headers: { host } }, origins)).toBeNull()
    }
  })

  it('takes public origins from AGENT_HUB_PUBLIC_ORIGINS', () => {
    const custom = allowedOrigins(3003, {
      AGENT_HUB_PUBLIC_ORIGINS: 'https://hub.example/',
    })
    expect(custom.has('https://hub.example')).toBe(true)
    expect(custom.has('https://agent.summitflow.dev')).toBe(false)
    expect(
      refusal({ method: 'GET', headers: { host: 'hub.example' } }, custom),
    ).toBeNull()
  })
})
