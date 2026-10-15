/**
 * Agent Hub frontend server: Next.js plus a trusted client-address header.
 *
 * Next.js only fills X-Forwarded-For when the client did not send one, so the
 * route handlers cannot tell the real TCP peer. This wrapper overwrites
 * x-agent-hub-client-address on every request (HTTP and WebSocket upgrade)
 * from the socket peer before Next.js sees it; the API proxy forwards it and
 * the backend decides local-owner trust from it, never from Host. Requests
 * from other sites (foreign Host or Origin) are refused first.
 */
import { createServer } from 'node:http'
import next from 'next'
import { CLIENT_ADDRESS_HEADER, clientAddress } from './src/lib/client-address.mjs'
import { allowedOrigins, refusal } from './src/lib/request-guard.mjs'

function arg(name, fallback) {
  const index = process.argv.indexOf(name)
  return index > -1 && process.argv[index + 1] ? process.argv[index + 1] : fallback
}

const hostname = arg('--hostname', arg('-H', process.env.HOSTNAME || '0.0.0.0'))
const port = Number(arg('--port', arg('-p', process.env.PORT || '3000')))

function stamp(req) {
  req.headers[CLIENT_ADDRESS_HEADER] = clientAddress(req.socket.remoteAddress, req.headers)
}

const origins = allowedOrigins(port)

const app = next({ dev: false, hostname, port })
const handle = app.getRequestHandler()
await app.prepare()
const upgrade = app.getUpgradeHandler()

const server = createServer((req, res) => {
  const refused = refusal(req, origins)
  if (refused) {
    res.writeHead(refused.status, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ error: refused.error }))
    return
  }
  stamp(req)
  handle(req, res)
})
server.on('upgrade', (req, socket, head) => {
  const refused = refusal({ headers: req.headers, upgrade: true }, origins)
  if (refused) {
    socket.end(`HTTP/1.1 ${refused.status} ${refused.error}\r\nConnection: close\r\n\r\n`)
    return
  }
  stamp(req)
  upgrade(req, socket, head)
})
server.listen(port, hostname, () => {
  console.log(`> Agent Hub frontend ready on http://${hostname}:${port}`)
})
