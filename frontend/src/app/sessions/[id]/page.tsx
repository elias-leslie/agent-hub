"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowLeft,
  MessageSquare,
  Clock,
  Cpu,
  Server,
  User,
  Bot,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Gauge,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchSession, type SessionMessage, type ContextUsage } from "@/lib/api";
import { useState } from "react";

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleString();
}

function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return tokens.toString();
}

function getProviderIcon(provider: string) {
  if (provider === "claude") {
    return <Cpu className="h-5 w-5 text-orange-600 dark:text-orange-400" />;
  }
  return <Server className="h-5 w-5 text-blue-600 dark:text-blue-400" />;
}

// Context usage bar
function ContextUsageBar({ usage }: { usage: ContextUsage }) {
  const percent = Math.min(100, usage.percent_used);
  const isWarning = percent > 70;
  const isDanger = percent > 90;

  return (
    <div className="p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Gauge className="h-4 w-4 text-slate-500" />
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
            Context Usage
          </span>
        </div>
        <span className="text-sm font-mono text-slate-600 dark:text-slate-400">
          {formatTokens(usage.used_tokens)} / {formatTokens(usage.limit_tokens)}
        </span>
      </div>
      <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            isDanger
              ? "bg-red-500"
              : isWarning
                ? "bg-amber-500"
                : "bg-emerald-500"
          )}
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
        <span>{percent.toFixed(1)}% used</span>
        <span>{formatTokens(usage.remaining_tokens)} remaining</span>
      </div>
      {usage.warning && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
          <AlertCircle className="h-3.5 w-3.5" />
          <span>{usage.warning}</span>
        </div>
      )}
    </div>
  );
}

// Message component
function MessageItem({
  message,
  isExpanded,
  onToggle,
}: {
  message: SessionMessage;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const isUser = message.role === "user";
  const isLong = message.content.length > 500;
  const displayContent =
    isExpanded || !isLong
      ? message.content
      : message.content.slice(0, 500) + "...";

  return (
    <div
      className={cn(
        "flex gap-3 p-4 rounded-lg",
        isUser
          ? "bg-blue-50 dark:bg-blue-950/30"
          : "bg-slate-50 dark:bg-slate-900/50"
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center",
          isUser
            ? "bg-blue-500 text-white"
            : "bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400"
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300 capitalize">
            {message.role}
          </span>
          <span className="text-xs text-slate-400">
            {formatDate(message.created_at)}
          </span>
          {message.tokens && (
            <span className="text-xs text-slate-400 font-mono">
              {message.tokens} tokens
            </span>
          )}
        </div>
        <div className="text-sm text-slate-600 dark:text-slate-400 whitespace-pre-wrap break-words">
          {displayContent}
        </div>
        {isLong && (
          <button
            onClick={onToggle}
            className="mt-2 flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400 hover:underline"
          >
            {isExpanded ? (
              <>
                <ChevronUp className="h-3 w-3" />
                Show less
              </>
            ) : (
              <>
                <ChevronDown className="h-3 w-3" />
                Show more
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
}

export default function SessionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [expandedMessages, setExpandedMessages] = useState<Set<number>>(
    new Set()
  );

  const { data: session, isLoading, error } = useQuery({
    queryKey: ["session", id],
    queryFn: () => fetchSession(id),
  });

  const toggleMessage = (messageId: number) => {
    setExpandedMessages((prev) => {
      const next = new Set(prev);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Header */}
      <header className="sticky top-0 z-10 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-4">
              <Link
                href="/sessions"
                className="p-2 -ml-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <ArrowLeft className="h-5 w-5 text-slate-500" />
              </Link>
              {session && (
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800">
                    {getProviderIcon(session.provider)}
                  </div>
                  <div>
                    <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100 font-mono">
                      {id.slice(0, 8)}...
                    </h1>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {session.model}
                    </p>
                  </div>
                </div>
              )}
            </div>

            {session && (
              <div className="flex items-center gap-3 text-sm text-slate-500 dark:text-slate-400">
                <div className="flex items-center gap-1">
                  <MessageSquare className="h-4 w-4" />
                  <span>{session.messages?.length ?? 0} messages</span>
                </div>
                <div className="flex items-center gap-1">
                  <Clock className="h-4 w-4" />
                  <span>{formatDate(session.created_at)}</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Error State */}
        {error && (
          <div className="flex items-center gap-2 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400">
            <AlertCircle className="h-5 w-5" />
            <p className="text-sm">Failed to load session</p>
          </div>
        )}

        {/* Loading State */}
        {isLoading && (
          <div className="flex items-center justify-center py-12 text-slate-500">
            Loading session...
          </div>
        )}

        {/* Session Content */}
        {session && (
          <div className="space-y-6">
            {/* Context Usage */}
            {session.context_usage && (
              <ContextUsageBar usage={session.context_usage} />
            )}

            {/* Session Info */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-3 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700">
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Project
                </p>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-300 truncate">
                  {session.project_id}
                </p>
              </div>
              <div className="p-3 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700">
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Provider
                </p>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-300 capitalize">
                  {session.provider}
                </p>
              </div>
              <div className="p-3 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700">
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Status
                </p>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-300 capitalize">
                  {session.status}
                </p>
              </div>
              <div className="p-3 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700">
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Updated
                </p>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
                  {formatDate(session.updated_at)}
                </p>
              </div>
            </div>

            {/* Messages */}
            <div>
              <h2 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-4">
                Messages ({session.messages?.length ?? 0})
              </h2>
              {session.messages?.length === 0 ? (
                <div className="text-center py-12 text-slate-500 dark:text-slate-400 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700">
                  <MessageSquare className="h-12 w-12 mx-auto mb-3 opacity-30" />
                  <p>No messages in this session</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {session.messages?.map((message) => (
                    <MessageItem
                      key={message.id}
                      message={message}
                      isExpanded={expandedMessages.has(message.id)}
                      onToggle={() => toggleMessage(message.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
