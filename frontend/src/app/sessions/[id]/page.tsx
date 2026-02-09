"use client";

import { use, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchSession, fetchSessionEvents } from "@/lib/api";
import { EventTimeline } from "@/components/timeline";
import { SessionHeader } from "./components/SessionHeader";
import { SessionInfo } from "./components/SessionInfo";

export default function SessionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [activeTab, setActiveTab] = useState<"timeline" | "info">("timeline");

  const {
    data: session,
    isLoading: sessionLoading,
    error: sessionError,
  } = useQuery({
    queryKey: ["session", id],
    queryFn: () => fetchSession(id),
  });

  const {
    data: eventsData,
    isLoading: eventsLoading,
    error: eventsError,
  } = useQuery({
    queryKey: ["session-events", id],
    queryFn: () => fetchSessionEvents(id, { page_size: 500 }),
  });

  const isLoading = sessionLoading || eventsLoading;
  const error = sessionError || eventsError;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Header */}
      {session && (
        <SessionHeader
          session={session}
          sessionId={id}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          eventsTotal={eventsData?.total}
          maxTurn={eventsData?.max_turn}
        />
      )}

      {/* Main content */}
      <main className="h-[calc(100vh-3.5rem)]">
        {/* Error State */}
        {error && (
          <div className="p-6">
            <div
              className={cn(
                "flex items-center gap-2 p-4 rounded-lg",
                "bg-red-950/40 border border-red-800/50",
                "text-red-400"
              )}
            >
              <AlertCircle className="h-5 w-5" />
              <p className="text-sm">Failed to load session</p>
            </div>
          </div>
        )}

        {/* Loading State */}
        {isLoading && (
          <div className="flex items-center justify-center h-full">
            <div className="flex flex-col items-center gap-3 text-slate-500">
              <div className="w-8 h-8 border-2 border-slate-700 border-t-slate-400 rounded-full animate-spin" />
              <p className="text-sm">Loading session...</p>
            </div>
          </div>
        )}

        {/* Content */}
        {!isLoading && !error && session && (
          <>
            {activeTab === "timeline" && eventsData && (
              <EventTimeline events={eventsData.events} className="h-full" />
            )}
            {activeTab === "info" && <SessionInfo session={session} />}
          </>
        )}
      </main>
    </div>
  );
}
