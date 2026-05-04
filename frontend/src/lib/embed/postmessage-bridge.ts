/**
 * PostMessage bridge for Agent Hub embed mode.
 *
 * Handles bidirectional communication between
 * the embedded Agent Hub iframe and its host window.
 */

// ── Inbound messages (host → iframe) ───────────────────

export type EmbedInboundMessage =
  | { type: 'set_agent'; payload: { agentSlug: string } }
  | { type: 'set_project'; payload: { projectId: string } }
  | { type: 'send_message'; payload: { message: string } }
  | { type: 'set_session'; payload: { sessionId: string } }

// ── Outbound messages (iframe → host) ──────────────────

export type EmbedOutboundMessage =
  | { type: 'ready' }
  | { type: 'session_created'; payload: { sessionId: string } }
  | { type: 'message_received'; payload: { role: string; content: string } }
  | { type: 'status_changed'; payload: { status: string } }
  | { type: 'error'; payload: { message: string } }

type InboundHandler = (msg: EmbedInboundMessage) => void

/**
 * Check if we're running inside an iframe.
 */
export function isEmbedded(): boolean {
  try {
    return window.self !== window.top
  } catch {
    return true // cross-origin iframe blocks access
  }
}

/**
 * Listen for inbound postMessage commands from the host.
 * Returns a cleanup function to remove the listener.
 */
export function listenForHostMessages(
  handler: InboundHandler,
  allowedOrigins?: string[],
): () => void {
  function onMessage(event: MessageEvent) {
    // Origin validation
    if (allowedOrigins && allowedOrigins.length > 0) {
      if (!allowedOrigins.includes(event.origin) && event.origin !== '*') {
        return
      }
    }

    const data = event.data
    if (!data || typeof data.type !== 'string') return

    // Validate known message types
    const validTypes = [
      'set_agent',
      'set_project',
      'send_message',
      'set_session',
    ]
    if (!validTypes.includes(data.type)) return

    handler(data as EmbedInboundMessage)
  }

  window.addEventListener('message', onMessage)
  return () => window.removeEventListener('message', onMessage)
}

/**
 * Send a message to the host window.
 */
export function sendToHost(
  message: EmbedOutboundMessage,
  targetOrigin = '*',
): void {
  if (!window.parent || window.parent === window) return
  window.parent.postMessage(message, targetOrigin)
}

// ── Host-side helper (for consumers embedding Agent Hub) ──

export interface EmbedClientConfig {
  /** The iframe element containing Agent Hub */
  iframe: HTMLIFrameElement
  /** Target origin for postMessage (default: "*") */
  targetOrigin?: string
}

/**
 * Create an embed client for communicating with the Agent Hub iframe.
 * Used by host applications (SummitFlow, Portfolio-AI, etc.)
 */
export function createEmbedClient(config: EmbedClientConfig) {
  const { iframe, targetOrigin = '*' } = config

  function send(msg: EmbedInboundMessage) {
    iframe.contentWindow?.postMessage(msg, targetOrigin)
  }

  function onMessage(handler: (msg: EmbedOutboundMessage) => void): () => void {
    function listener(event: MessageEvent) {
      if (event.source !== iframe.contentWindow) return
      const data = event.data
      if (!data || typeof data.type !== 'string') return
      handler(data as EmbedOutboundMessage)
    }
    window.addEventListener('message', listener)
    return () => window.removeEventListener('message', listener)
  }

  return {
    setAgent: (agentSlug: string) =>
      send({ type: 'set_agent', payload: { agentSlug } }),
    setProject: (projectId: string) =>
      send({ type: 'set_project', payload: { projectId } }),
    sendMessage: (message: string) =>
      send({ type: 'send_message', payload: { message } }),
    setSession: (sessionId: string) =>
      send({ type: 'set_session', payload: { sessionId } }),
    onMessage,
  }
}
