"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Loader2, AlertCircle } from "lucide-react";
import { PlaygroundHeader } from "./components/PlaygroundHeader";
import { ChatInterface } from "./components/ChatInterface";
import { DebugPanel } from "./components/DebugPanel";
import { usePlaygroundChat } from "./hooks/usePlaygroundChat";
import { useAutoScroll } from "./hooks/useAutoScroll";
import { fetchAgent, fetchAgents, fetchPreview } from "./api";

// ─────────────────────────────────────────────────────────────────────────────
// MAIN PAGE
// ─────────────────────────────────────────────────────────────────────────────

export default function PlaygroundPage() {
  const params = useParams();
  const router = useRouter();
  const initialSlug = params.slug as string;
  const [selectedSlug, setSelectedSlug] = useState(initialSlug);

  const { data: agent, isLoading: agentLoading } = useQuery({
    queryKey: ["agent", selectedSlug],
    queryFn: () => fetchAgent(selectedSlug),
    enabled: !!selectedSlug,
  });

  const { data: agentsData } = useQuery({
    queryKey: ["agents-list"],
    queryFn: fetchAgents,
  });

  const { data: preview } = useQuery({
    queryKey: ["agent-preview", selectedSlug],
    queryFn: () => fetchPreview(selectedSlug),
    enabled: !!selectedSlug,
  });

  const {
    messages,
    input,
    setInput,
    isLoading,
    debugTrace,
    messagesEndRef,
    inputRef,
    handleSubmit,
    handleKeyDown,
    clearChat,
  } = usePlaygroundChat(selectedSlug, agent, preview);

  useAutoScroll(messagesEndRef, messages);

  // Focus input on load
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSelectAgent = (slug: string) => {
    setSelectedSlug(slug);
    clearChat();
  };

  if (agentLoading) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="h-10 w-10 text-red-500 mx-auto mb-3" />
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Agent not found
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-slate-50 dark:bg-slate-950">
      <PlaygroundHeader
        agent={agent}
        selectedSlug={selectedSlug}
        initialSlug={initialSlug}
        agents={agentsData?.agents}
        onBack={() => router.push(`/agents/${initialSlug}`)}
        onSelectAgent={handleSelectAgent}
        onClearChat={clearChat}
      />

      <div className="flex-1 flex overflow-hidden">
        <ChatInterface
          ref={inputRef}
          agent={agent}
          messages={messages}
          input={input}
          isLoading={isLoading}
          messagesEndRef={messagesEndRef}
          onInputChange={setInput}
          onSubmit={handleSubmit}
          onKeyDown={handleKeyDown}
        />

        <DebugPanel
          agent={agent}
          preview={preview}
          debugTrace={debugTrace}
          messages={messages}
        />
      </div>
    </div>
  );
}
