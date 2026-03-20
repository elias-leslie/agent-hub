"use client";

import { useParams } from "next/navigation";
import { AgentArenaDashboard } from "./components/AgentArenaDashboard";

export default function AgentArenaPage() {
  const params = useParams();
  const slug = params.slug as string;
  return <AgentArenaDashboard slug={slug} />;
}
