import { describe, expect, it } from 'vitest'
import { clientAddress } from '@/lib/client-address.mjs'

describe('frontend server client address', () => {
  it('uses a LAN or remote peer and ignores its forwarding headers', () => {
    const spoofed = {
      host: 'localhost',
      'x-forwarded-for': '127.0.0.1',
      'cf-connecting-ip': '127.0.0.1',
      'x-agent-hub-client-address': '127.0.0.1',
    }
    expect(clientAddress('203.0.113.5', spoofed)).toBe('203.0.113.5')
    expect(clientAddress('::ffff:192.168.86.50', spoofed)).toBe('192.168.86.50')
  })

  it('trusts forwarding headers only from a loopback peer such as cloudflared', () => {
    expect(
      clientAddress('127.0.0.1', {
        'cf-connecting-ip': '198.51.100.7',
        'x-forwarded-for': '10.0.0.1',
      }),
    ).toBe('198.51.100.7')
    expect(
      clientAddress('::1', { 'x-forwarded-for': '198.51.100.8, 127.0.0.1' }),
    ).toBe('198.51.100.8')
    expect(clientAddress('127.0.0.1', {})).toBe('127.0.0.1')
  })

  it('reports a missing peer as unknown', () => {
    expect(clientAddress(undefined, {})).toBe('unknown')
  })
})
