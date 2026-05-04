'use client'

import { AgentArenaDashboard } from '@/app/agents/[slug]/arena/components/AgentArenaDashboard'

interface AgentAnalyticsDashboardProps {
  slug: string
  backHref?: string
}

export function AgentAnalyticsDashboard({
  slug,
  backHref,
}: AgentAnalyticsDashboardProps) {
  return (
    <AgentArenaDashboard
      slug={slug}
      backHref={backHref}
      initialView="runtime"
    />
  )
}
