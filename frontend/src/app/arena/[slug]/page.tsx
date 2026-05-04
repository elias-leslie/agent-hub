'use client'

import { useParams } from 'next/navigation'
import { AgentArenaDashboard } from '@/app/agents/[slug]/arena/components/AgentArenaDashboard'

export default function ArenaAgentPage() {
  const params = useParams()
  const slug = params.slug as string
  return <AgentArenaDashboard slug={slug} backHref="/arena" />
}
