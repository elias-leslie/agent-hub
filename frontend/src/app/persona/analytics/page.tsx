"use client";

import { AgentAnalyticsDashboard } from "@/app/agents/[slug]/analytics/components/AgentAnalyticsDashboard";

export default function PersonaAnalyticsPage() {
  return <AgentAnalyticsDashboard slug="persona" backHref="/persona" />;
}
