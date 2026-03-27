"use client";

import { Loader2, MessageSquarePlus } from "lucide-react";
import { MessageInput } from "@agent-hub/chat-ui";
import { fetchApi, getApiBaseUrl, getWsUrl } from "@/lib/api-config";

interface WorkspaceChatFooterProps {
  responseStatusLabel: string | null;
  status: string;
  sendMessage: (content: string) => void;
  cancelStream: () => void;
  preferencesEndpoint: string;
  onNewSession: () => void;
}

export function WorkspaceChatFooter({
  responseStatusLabel,
  status,
  sendMessage,
  cancelStream,
  preferencesEndpoint,
  onNewSession,
}: WorkspaceChatFooterProps) {
  return (
    <div className="border-t border-slate-800/50 bg-[#0d0e13]/95 px-5 py-3 backdrop-blur-lg">
      <div className="mx-auto max-w-3xl">
        <div className="mb-2 flex items-center justify-between text-[11px] text-slate-500">
          <div className="flex items-center gap-2">
            {responseStatusLabel && (
              <span className="inline-flex items-center gap-1.5 text-amber-400/80">
                <Loader2 className="h-3 w-3 animate-spin" />
                {responseStatusLabel}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onNewSession}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-slate-600 transition-all hover:bg-slate-800/50 hover:text-slate-400"
          >
            <MessageSquarePlus className="h-3 w-3" />
            New thread
          </button>
        </div>
        <MessageInput
          onSend={sendMessage}
          onCancel={cancelStream}
          status={status as Parameters<typeof MessageInput>[0]["status"]}
          voiceWsUrl={getWsUrl("/api/voice/ws?user_id=agent_hub_user&app=agent-hub&mode=transcribe")}
          ttsBaseUrl={getApiBaseUrl() || window.location.origin}
          preferencesEndpoint={preferencesEndpoint}
          fetchFn={fetchApi}
        />
      </div>
    </div>
  );
}
