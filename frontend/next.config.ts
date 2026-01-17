import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // Rewrite /api/* to backend
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `http://localhost:8003/api/:path*`,
      },
    ]
  },

  // Disable x-powered-by header
  poweredByHeader: false,

  // Enable React strict mode
  reactStrictMode: true,
}

export default nextConfig
