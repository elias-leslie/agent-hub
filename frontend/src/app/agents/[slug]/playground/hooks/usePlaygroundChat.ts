import { useState, useRef, useCallback } from "react";
import { fetchApi } from "@/lib/api-config";
import type { Agent, AgentPreview, Message, DebugTrace } from "../types";

export function usePlaygroundChat(
  selectedSlug: string,
  agent: Agent | undefined,
  preview: AgentPreview | undefined
) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [debugTrace, setDebugTrace] = useState<DebugTrace | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = useCallback(async () => {
    if (!input.trim() || isLoading || !agent) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content: input.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    try {
      const startTime = performance.now();

      const res = await fetchApi("/api/complete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Source-Client": "agent-hub-playground",
          "X-Source-Path": `/agents/${selectedSlug}/playground`,
        },
        body: JSON.stringify({
          model: agent.primary_model_id,
          agent_slug: selectedSlug,
          project_id: "agent-playground",
          messages: [
            ...messages.map((m) => ({ role: m.role, content: m.content })),
            { role: "user", content: userMessage.content },
          ],
        }),
      });

      const endTime = performance.now();

      if (!res.ok) {
        throw new Error("API request failed");
      }

      const data = await res.json();
      const assistantContent = data.content ?? "No response";

      const assistantMessage: Message = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: assistantContent,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, assistantMessage]);

      setDebugTrace({
        model_used: data.model_used ?? data.model ?? agent.primary_model_id,
        input_tokens: data.usage?.input_tokens ?? 0,
        output_tokens: data.usage?.output_tokens ?? 0,
        latency_ms: Math.round(endTime - startTime),
        mandates_injected: preview?.mandate_count ?? 0,
        mandate_uuids: preview?.mandate_uuids ?? [],
        combined_prompt_length: preview?.combined_prompt?.length ?? 0,
      });
    } catch (error) {
      console.error("Completion error:", error);
      setMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: "Sorry, an error occurred. Please try again.",
          timestamp: new Date(),
        },
      ]);
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  }, [input, isLoading, agent, messages, selectedSlug, preview]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  const clearChat = useCallback(() => {
    setMessages([]);
    setDebugTrace(null);
  }, []);

  return {
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
  };
}
