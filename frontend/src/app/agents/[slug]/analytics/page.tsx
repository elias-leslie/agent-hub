'use client'

import { useParams } from 'next/navigation'
import { AgentAnalyticsDashboard } from './components/AgentAnalyticsDashboard'

export default function AgentAnalyticsPage() {
  const params = useParams()
  const slug = params.slug as string
  return <AgentAnalyticsDashboard slug={slug} />
}
