import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // API routing is handled client-side via lib/api-config.ts
  // No rewrites needed - getWsUrl() and buildApiUrl() resolve to correct backend URL
  // based on window.location (localhost for dev, agentapi.summitflow.dev for prod)

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

  // Disable x-powered-by header
  poweredByHeader: false,

  // Enable React strict mode
  reactStrictMode: true,
}

export default nextConfig
