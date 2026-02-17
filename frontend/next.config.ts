import type { NextConfig } from 'next'

const AGENT_HUB_API_URL =
  process.env.AGENT_HUB_API_URL || 'http://localhost:8003'
const SUMMITFLOW_API_URL =
  process.env.SUMMITFLOW_API_URL || 'http://localhost:8001'

const nextConfig: NextConfig = {
  // Proxy /api/* to backend server-to-server to avoid CORS issues with CF Access
  // In production: browser requests agent.summitflow.dev/api/* (same-origin)
  // Next.js rewrites proxy to backend (server-to-server, no CORS)
  async rewrites() {
    return [
      // Agent Hub backend API (same-origin for CF Access compatibility)
      {
        source: '/api/:path*',
        destination: `${AGENT_HUB_API_URL}/api/:path*`,
      },
      // SummitFlow API proxy (cross-project calls via same-origin)
      // Handles /summitflow-api/api/* -> SummitFlow backend /api/*
      {
        source: '/summitflow-api/api/:path*',
        destination: `${SUMMITFLOW_API_URL}/api/:path*`,
      },
    ]
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
    ]
  },

  // Transpile workspace packages
  transpilePackages: ['@agent-hub/passport-client', '@agent-hub/chat-ui'],

  // Disable x-powered-by header
  poweredByHeader: false,

  // Enable React strict mode
  reactStrictMode: true,
}

export default nextConfig
