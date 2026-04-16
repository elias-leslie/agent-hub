import type { NextConfig } from 'next'
import { PORTS } from './src/lib/api-config'

const AGENT_HUB_API_URL =
  process.env.AGENT_HUB_API_URL || `http://localhost:${PORTS.backend}`
const SUMMITFLOW_API_URL =
  process.env.SUMMITFLOW_API_URL || 'http://localhost:8001'

const nextConfig: NextConfig = {
  output: 'standalone',
  async redirects() {
    return [
      {
        source: '/',
        destination: '/dashboard',
        permanent: false,
      },
    ]
  },

  // Proxy API requests through route handlers for auth header injection.
  // /api/proxy/* is handled by the auth proxy route handler (injects X-Client-Id).
  // Direct /api/* rewrites can't inject headers, so we use beforeFiles to
  // route through the proxy handler first.
  async rewrites() {
    return {
      // beforeFiles: WebSocket-capable paths must go directly to the backend
      // (route handlers can't proxy WebSocket upgrades).
      beforeFiles: [
        // Notes API -> SummitFlow backend (centralized shared notes service)
        {
          source: '/api/notes/:path*',
          destination: `${SUMMITFLOW_API_URL}/api/notes/:path*`,
        },
        {
          source: '/api/notes',
          destination: `${SUMMITFLOW_API_URL}/api/notes`,
        },
        // WebSocket: session events
        {
          source: '/api/events',
          destination: `${AGENT_HUB_API_URL}/api/events`,
        },
        // WebSocket: voice transcription
        {
          source: '/api/voice/:path*',
          destination: `${AGENT_HUB_API_URL}/api/voice/:path*`,
        },
      ],
      // afterFiles: existing file-based routes (e.g. /api/memory/*) resolve first,
      // then unmatched /api/* requests go through the auth proxy handler.
      afterFiles: [
        {
          source: '/api/:path((?!proxy/).*)',
          destination: '/api/proxy/:path*',
        },
      ],
      fallback: [
        // SummitFlow API proxy (cross-project calls via same-origin)
        {
          source: '/summitflow-api/api/:path*',
          destination: `${SUMMITFLOW_API_URL}/api/:path*`,
        },
      ],
    }
  },

  // PWA headers for service worker and manifest
  async headers() {
    return [
      {
        source: '/sw.js',
        headers: [
          {
            key: 'Cache-Control',
            value: 'no-cache, no-store, must-revalidate',
          },
          {
            key: 'Service-Worker-Allowed',
            value: '/',
          },
        ],
      },
      {
        source: '/manifest.json',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=3600',
          },
        ],
      },
      // Allow embedding /embed routes in iframes from known origins
      {
        source: '/embed/:path*',
        headers: [
          {
            key: 'X-Frame-Options',
            value: 'ALLOWALL',
          },
          {
            key: 'Content-Security-Policy',
            value: 'frame-ancestors *',
          },
        ],
      },
    ]
  },

  // Transpile workspace packages
  transpilePackages: [
    '@agent-hub/passport-client',
    '@agent-hub/chat-ui',
    '@summitflow/notes-ui',
  ],

  // Disable x-powered-by header
  poweredByHeader: false,

  // Enable React strict mode
  reactStrictMode: true,
}

export default nextConfig
