import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // Proxy /api/* to backend server-to-server to avoid CORS issues with CF Access
  // In production: browser requests agent.summitflow.dev/api/* (same-origin)
  // Next.js rewrites proxy to localhost:8003 (server-to-server, no CORS)
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8003/api/:path*',
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

  // Disable x-powered-by header
  poweredByHeader: false,

  // Enable React strict mode
  reactStrictMode: true,
}

export default nextConfig
