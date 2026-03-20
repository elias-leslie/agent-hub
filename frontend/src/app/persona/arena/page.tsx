"use client";

import { AgentArenaDashboard } from "@/app/agents/[slug]/arena/components/AgentArenaDashboard";

export default function PersonaArenaPage() {
  return <AgentArenaDashboard slug="persona" backHref="/persona" />;
}
