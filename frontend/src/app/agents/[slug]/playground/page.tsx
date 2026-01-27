"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  Send,
  ArrowLeft,
  ChevronRight,
  ChevronDown,
  Loader2,
  User,
  Clock,
  Zap,
  FileText,
  AlertCircle,
  Cpu,
  Hash,
  Tag,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchApi } from "@/lib/api-config";

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

interface Agent {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  system_prompt: string;
  primary_model_id: string;
  fallback_models: string[];
  temperature: number;
}

interface AgentPreview {
  slug: string;
  name: string;
  combined_prompt: string;
  mandate_count: number;
  mandate_uuids: string[];
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface DebugTrace {
  model_used: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  mandates_injected: number;
  mandate_uuids: string[];
  combined_prompt_length: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────────────────────────────────

async function fetchAgent(slug: string): Promise<Agent> {
  const res = await fetchApi(`/api/agents/${slug}`);
  if (!res.ok) throw new Error("Failed to fetch agent");
  return res.json();
}

async function fetchAgents(): Promise<{ agents: Agent[] }> {
  const res = await fetchApi("/api/agents?active_only=true");
  if (!res.ok) throw new Error("Failed to fetch agents");
  return res.json();
}

async function fetchPreview(slug: string): Promise<AgentPreview> {
  const res = await fetchApi(`/api/agents/${slug}/preview`);
  if (!res.ok) throw new Error("Failed to fetch preview");
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPONENTS
// ─────────────────────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex gap-3", isUser ? "justify-end" : "justify-start")}>
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gradient-to-br from-orange-500 to-amber-500 flex items-center justify-center">
          <Bot className="h-4 w-4 text-white" />
        </div>
      )}
      <div
        className={cn(
          "max-w-[70%] rounded-2xl px-4 py-2.5 text-sm",
          isUser
            ? "bg-blue-600 text-white rounded-br-sm"
            : "bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 rounded-bl-sm"
        )}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
        <p
          className={cn(
            "text-[10px] mt-1 opacity-60",
            isUser ? "text-right" : "text-left"
          )}
        >
          {message.timestamp.toLocaleTimeString()}
        </p>
      </div>
      {isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center">
          <User className="h-4 w-4 text-slate-600 dark:text-slate-400" />
        </div>
      )}
    </div>
  );
}

function DebugSection({
  title,
  icon: Icon,
  children,
  defaultOpen = true,
}: {
  title: string;
  icon: React.ElementType;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="border-b border-slate-200 dark:border-slate-700 last:border-b-0">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 w-full px-4 py-3 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
      >
        {isOpen ? (
          <ChevronDown className="h-4 w-4 text-slate-400" />
        ) : (
          <ChevronRight className="h-4 w-4 text-slate-400" />
        )}
        <Icon className="h-4 w-4 text-slate-500" />
        <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
          {title}
        </span>
      </button>
      {isOpen && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

function StatItem({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div className="flex justify-between items-center py-1">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-xs font-mono font-semibold text-slate-700 dark:text-slate-300">
        {value}
        {unit && <span className="text-slate-400 ml-0.5">{unit}</span>}
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN PAGE
// ─────────────────────────────────────────────────────────────────────────────

export default function PlaygroundPage() {
  const params = useParams();
  const router = useRouter();
  const initialSlug = params.slug as string;

  const [selectedSlug, setSelectedSlug] = useState(initialSlug);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [debugTrace, setDebugTrace] = useState<DebugTrace | null>(null);
  const [showPrompt, setShowPrompt] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

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

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input on load
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

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

      // Call the native completion API with agent_slug for full routing
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

      // Update debug trace with native API response fields
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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const clearChat = () => {
    setMessages([]);
    setDebugTrace(null);
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
      {/* HEADER */}
      <header className="flex-shrink-0 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
        <div className="px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.push(`/agents/${initialSlug}`)}
              className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              <ArrowLeft className="h-5 w-5 text-slate-600 dark:text-slate-400" />
            </button>

            <div className="flex items-center gap-3">
              <Bot className="h-5 w-5 text-slate-600 dark:text-slate-400" />
              <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                Playground
              </span>

              {/* Agent Selector */}
              <select
                value={selectedSlug}
                onChange={(e) => {
                  setSelectedSlug(e.target.value);
                  clearChat();
                }}
                className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              >
                {agentsData?.agents.map((a) => (
                  <option key={a.slug} value={a.slug}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <button
            onClick={clearChat}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Clear
          </button>
        </div>
      </header>

      {/* MAIN CONTENT - SPLIT VIEW */}
      <div className="flex-1 flex overflow-hidden">
        {/* LEFT PANE - CHAT */}
        <div className="flex-1 flex flex-col min-w-0 border-r border-slate-200 dark:border-slate-800">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.length === 0 ? (
              <div className="h-full flex items-center justify-center">
                <div className="text-center">
                  <Bot className="h-12 w-12 text-slate-300 dark:text-slate-600 mx-auto mb-3" />
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    Start a conversation with <span className="font-semibold">{agent.name}</span>
                  </p>
                  <p className="text-xs text-slate-400 mt-1">
                    Using {agent.primary_model_id}
                  </p>
                </div>
              </div>
            ) : (
              messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))
            )}
            {isLoading && (
              <div className="flex gap-3">
                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gradient-to-br from-orange-500 to-amber-500 flex items-center justify-center">
                  <Bot className="h-4 w-4 text-white" />
                </div>
                <div className="bg-slate-100 dark:bg-slate-800 rounded-2xl rounded-bl-sm px-4 py-3">
                  <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="flex-shrink-0 border-t border-slate-200 dark:border-slate-800 p-4 bg-white dark:bg-slate-900">
            <div className="flex gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type a message..."
                rows={1}
                className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              />
              <button
                onClick={handleSubmit}
                disabled={!input.trim() || isLoading}
                className="px-4 py-2.5 rounded-xl bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        {/* RIGHT PANE - DEBUG */}
        <div className="w-80 flex-shrink-0 overflow-y-auto bg-white dark:bg-slate-900">
          <div className="sticky top-0 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700 px-4 py-3">
            <h2 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Debug Trace
            </h2>
          </div>

          {/* Model Info */}
          <DebugSection title="Model" icon={Cpu}>
            <div className="space-y-1">
              <StatItem label="Primary" value={agent.primary_model_id} />
              {agent.fallback_models.length > 0 && (
                <StatItem
                  label="Fallbacks"
                  value={agent.fallback_models.join(", ")}
                />
              )}
              <StatItem label="Temperature" value={agent.temperature.toFixed(2)} />
            </div>
          </DebugSection>

          {/* Last Request Stats */}
          {debugTrace && (
            <DebugSection title="Last Request" icon={Zap}>
              <div className="space-y-1">
                <StatItem label="Model Used" value={debugTrace.model_used} />
                <StatItem label="Latency" value={debugTrace.latency_ms} unit="ms" />
                <StatItem label="Input Tokens" value={debugTrace.input_tokens} />
                <StatItem label="Output Tokens" value={debugTrace.output_tokens} />
                <StatItem
                  label="Total Tokens"
                  value={debugTrace.input_tokens + debugTrace.output_tokens}
                />
              </div>
            </DebugSection>
          )}

          {/* Memory Injection */}
          <DebugSection title="Memory" icon={Tag} defaultOpen={false}>
            <div className="space-y-2">
              {preview && (
                <StatItem
                  label="Injected Count"
                  value={preview.mandate_count}
                />
              )}
              {debugTrace && debugTrace.mandate_uuids.length > 0 && (
                <div className="mt-2">
                  <p className="text-[10px] text-slate-400 mb-1">UUIDs:</p>
                  <div className="space-y-0.5">
                    {debugTrace.mandate_uuids.slice(0, 5).map((uuid) => (
                      <p
                        key={uuid}
                        className="text-[10px] font-mono text-slate-500 truncate"
                      >
                        {uuid}
                      </p>
                    ))}
                    {debugTrace.mandate_uuids.length > 5 && (
                      <p className="text-[10px] text-slate-400">
                        +{debugTrace.mandate_uuids.length - 5} more
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          </DebugSection>

          {/* Combined Prompt */}
          <DebugSection title="Combined Prompt" icon={FileText} defaultOpen={false}>
            {preview ? (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-slate-500">Length</span>
                  <span className="text-xs font-mono text-slate-700 dark:text-slate-300">
                    {preview.combined_prompt.length} chars
                  </span>
                </div>
                <button
                  onClick={() => setShowPrompt(!showPrompt)}
                  className="text-xs text-blue-600 hover:underline"
                >
                  {showPrompt ? "Hide" : "Show"} full prompt
                </button>
                {showPrompt && (
                  <pre className="mt-2 p-2 rounded bg-slate-50 dark:bg-slate-800 text-[10px] font-mono text-slate-600 dark:text-slate-400 overflow-x-auto whitespace-pre-wrap max-h-60 overflow-y-auto">
                    {preview.combined_prompt}
                  </pre>
                )}
              </div>
            ) : (
              <p className="text-xs text-slate-400 italic">Loading...</p>
            )}
          </DebugSection>

          {/* Token Stats */}
          <DebugSection title="Session Stats" icon={Hash}>
            <div className="space-y-1">
              <StatItem label="Messages" value={messages.length} />
              <StatItem
                label="User Messages"
                value={messages.filter((m) => m.role === "user").length}
              />
              <StatItem
                label="Assistant Messages"
                value={messages.filter((m) => m.role === "assistant").length}
              />
            </div>
          </DebugSection>
        </div>
      </div>
    </div>
  );
}
