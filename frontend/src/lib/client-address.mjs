/**
 * Decide the real client address of a request reaching the frontend server.
 *
 * The TCP peer is authoritative. Forwarding headers are honoured only when the
 * peer is loopback, which is where cloudflared (and other local processes)
 * connect from: cloudflared sets Cf-Connecting-IP / X-Forwarded-For to the
 * internet client. A LAN or remote peer's own forwarding headers are ignored.
 *
 * @param {string | undefined} peer socket.remoteAddress
 * @param {Record<string, string | string[] | undefined>} headers incoming headers
 * @returns {string}
 */
export function clientAddress(peer, headers) {
  const address = normalize(peer)
  if (!isLoopback(address)) return address || 'unknown'
  const forwarded =
    first(headers['cf-connecting-ip']) ?? first(headers['x-forwarded-for'])
  return forwarded ? normalize(forwarded) : address
}

/** Header the frontend server sets (overwriting any client value). */
export const CLIENT_ADDRESS_HEADER = 'x-agent-hub-client-address'

/** @param {string | string[] | undefined} value */
function first(value) {
  const raw = Array.isArray(value) ? value[0] : value
  const item = raw?.split(',')[0]?.trim()
  return item || undefined
}

/** @param {string | undefined} value */
function normalize(value) {
  const text = (value ?? '').trim()
  return text.startsWith('::ffff:') ? text.slice(7) : text
}

/** @param {string} address */
function isLoopback(address) {
  return address === '::1' || address.startsWith('127.')
}
