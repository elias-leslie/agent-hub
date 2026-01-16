"use client";

import { useState } from "react";
import {
  PanelRightClose,
  PanelRightOpen,
  Database,
  FileText,
  MessageSquare,
  Gauge,
  Lightbulb,
  Plus,
  X,
  ChevronDown,
  ChevronUp,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface ContextSource {
  id: string;
  type: "message" | "system" | "memory" | "summary";
  label: string;
  content: string;
  tokens?: number;
  timestamp?: Date;
  originalContent?: string; // For summarized content
}

export interface TokenBudget {
  used: number;
  limit: number;
  inputTokens: number;
  outputTokens: number;
}

export interface StickyNote {
  id: string;
  content: string;
  createdAt: Date;
}

export interface ContextPanelProps {
  isOpen: boolean;
  onToggle: () => void;
  sources: ContextSource[];
  tokenBudget: TokenBudget;
  systemPrompt?: string;
  stickyNotes: StickyNote[];
  onAddNote: (content: string) => void;
  onRemoveNote: (id: string) => void;
}

function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`;
  return tokens.toLocaleString();
}

/**
 * Context visibility panel showing session context, token usage, and notes.
 */
export function ContextPanel({
  isOpen,
  onToggle,
  sources,
  tokenBudget,
  systemPrompt,
  stickyNotes,
  onAddNote,
  onRemoveNote,
}: ContextPanelProps) {
  const [newNote, setNewNote] = useState("");
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(["budget", "sources"]),
  );
  const [expandedSource, setExpandedSource] = useState<string | null>(null);

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      return next;
    });
  };

  const handleAddNote = () => {
    if (newNote.trim()) {
      onAddNote(newNote.trim());
      setNewNote("");
    }
  };

  const usagePercent = Math.min(
    100,
    (tokenBudget.used / tokenBudget.limit) * 100,
  );
  const isWarning = usagePercent > 70;
  const isDanger = usagePercent > 90;

  if (!isOpen) {
    return (
      <button
        onClick={onToggle}
        className="fixed right-4 top-20 z-20 p-2 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-lg hover:bg-slate-50 dark:hover:bg-slate-700"
        title="Show context panel"
      >
        <PanelRightOpen className="h-5 w-5 text-slate-600 dark:text-slate-400" />
      </button>
    );
  }

  return (
    <div className="w-80 border-l border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-slate-500" />
          <span className="font-medium text-slate-900 dark:text-slate-100">
            Context
          </span>
        </div>
        <button
          onClick={onToggle}
          className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <PanelRightClose className="h-4 w-4 text-slate-500" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Token Budget */}
        <Section
          title="Token Budget"
          icon={<Gauge className="h-4 w-4" />}
          isExpanded={expandedSections.has("budget")}
          onToggle={() => toggleSection("budget")}
          testId="context-section-budget"
        >
          <div className="space-y-3">
            {/* Progress bar */}
            <div>
              <div className="flex justify-between text-xs text-slate-500 dark:text-slate-400 mb-1">
                <span>{formatTokens(tokenBudget.used)} used</span>
                <span>{formatTokens(tokenBudget.limit)} limit</span>
              </div>
              <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full transition-all",
                    isDanger
                      ? "bg-red-500"
                      : isWarning
                        ? "bg-amber-500"
                        : "bg-emerald-500",
                  )}
                  style={{ width: `${usagePercent}%` }}
                />
              </div>
              <p
                className={cn(
                  "text-xs mt-1",
                  isDanger
                    ? "text-red-600 dark:text-red-400"
                    : isWarning
                      ? "text-amber-600 dark:text-amber-400"
                      : "text-slate-500 dark:text-slate-400",
                )}
              >
                {usagePercent.toFixed(1)}% used •{" "}
                {formatTokens(tokenBudget.limit - tokenBudget.used)} remaining
              </p>
            </div>

            {/* Breakdown */}
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="p-2 rounded bg-slate-50 dark:bg-slate-800">
                <p className="text-slate-500 dark:text-slate-400">Input</p>
                <p className="font-mono text-slate-700 dark:text-slate-300">
                  {formatTokens(tokenBudget.inputTokens)}
                </p>
              </div>
              <div className="p-2 rounded bg-slate-50 dark:bg-slate-800">
                <p className="text-slate-500 dark:text-slate-400">Output</p>
                <p className="font-mono text-slate-700 dark:text-slate-300">
                  {formatTokens(tokenBudget.outputTokens)}
                </p>
              </div>
            </div>
          </div>
        </Section>

        {/* System Prompt */}
        {systemPrompt && (
          <Section
            title="System Prompt"
            icon={<FileText className="h-4 w-4" />}
            isExpanded={expandedSections.has("system")}
            onToggle={() => toggleSection("system")}
            testId="context-section-system"
          >
            <p className="text-xs text-slate-600 dark:text-slate-400 whitespace-pre-wrap line-clamp-6">
              {systemPrompt}
            </p>
          </Section>
        )}

        {/* Context Sources */}
        <Section
          title="Context Sources"
          icon={<MessageSquare className="h-4 w-4" />}
          badge={sources.length}
          isExpanded={expandedSections.has("sources")}
          onToggle={() => toggleSection("sources")}
          testId="context-section-sources"
        >
          <div className="space-y-2">
            {sources.length === 0 ? (
              <p className="text-xs text-slate-500 dark:text-slate-400 text-center py-2">
                No context sources
              </p>
            ) : (
              sources.map((source) => (
                <ContextSourceItem
                  key={source.id}
                  source={source}
                  isExpanded={expandedSource === source.id}
                  onToggle={() =>
                    setExpandedSource(
                      expandedSource === source.id ? null : source.id,
                    )
                  }
                />
              ))
            )}
          </div>
        </Section>

        {/* Sticky Notes */}
        <Section
          title="Sticky Notes"
          icon={<Lightbulb className="h-4 w-4" />}
          badge={stickyNotes.length}
          isExpanded={expandedSections.has("notes")}
          onToggle={() => toggleSection("notes")}
          testId="context-section-notes"
        >
          <div className="space-y-2">
            {/* Add note input */}
            <div className="flex gap-2">
              <input
                type="text"
                value={newNote}
                onChange={(e) => setNewNote(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleAddNote()}
                placeholder="Add a note..."
                className="flex-1 px-2 py-1 text-xs rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800"
              />
              <button
                onClick={handleAddNote}
                disabled={!newNote.trim()}
                className="p-1 rounded bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50"
              >
                <Plus className="h-4 w-4" />
              </button>
            </div>

            {/* Notes list */}
            {stickyNotes.map((note) => (
              <div
                key={note.id}
                className="flex items-start gap-2 p-2 rounded bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800"
              >
                <Lightbulb className="h-3 w-3 text-amber-500 mt-0.5 flex-shrink-0" />
                <p className="flex-1 text-xs text-amber-800 dark:text-amber-200">
                  {note.content}
                </p>
                <button
                  onClick={() => onRemoveNote(note.id)}
                  className="p-0.5 rounded hover:bg-amber-200 dark:hover:bg-amber-800"
                >
                  <X className="h-3 w-3 text-amber-600 dark:text-amber-400" />
                </button>
              </div>
            ))}
          </div>
        </Section>
      </div>
    </div>
  );
}

interface SectionProps {
  title: string;
  icon: React.ReactNode;
  badge?: number;
  isExpanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  testId?: string;
}

function Section({
  title,
  icon,
  badge,
  isExpanded,
  onToggle,
  children,
  testId,
}: SectionProps) {
  return (
    <div className="border-b border-slate-200 dark:border-slate-800">
      <button
        data-testid={testId}
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50"
      >
        <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
          {icon}
          <span>{title}</span>
          {badge !== undefined && badge > 0 && (
            <span className="px-1.5 py-0.5 rounded-full text-xs bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400">
              {badge}
            </span>
          )}
        </div>
        {isExpanded ? (
          <ChevronUp className="h-4 w-4 text-slate-400" />
        ) : (
          <ChevronDown className="h-4 w-4 text-slate-400" />
        )}
      </button>
      {isExpanded && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

interface ContextSourceItemProps {
  source: ContextSource;
  isExpanded: boolean;
  onToggle: () => void;
}

function ContextSourceItem({
  source,
  isExpanded,
  onToggle,
}: ContextSourceItemProps) {
  const typeConfig = {
    message: {
      bg: "bg-blue-50 dark:bg-blue-900/20",
      border: "border-blue-200 dark:border-blue-800",
      icon: MessageSquare,
    },
    system: {
      bg: "bg-purple-50 dark:bg-purple-900/20",
      border: "border-purple-200 dark:border-purple-800",
      icon: FileText,
    },
    memory: {
      bg: "bg-emerald-50 dark:bg-emerald-900/20",
      border: "border-emerald-200 dark:border-emerald-800",
      icon: Database,
    },
    summary: {
      bg: "bg-amber-50 dark:bg-amber-900/20",
      border: "border-amber-200 dark:border-amber-800",
      icon: Clock,
    },
  };

  const config = typeConfig[source.type];
  const Icon = config.icon;

  return (
    <div className={cn("rounded border text-xs", config.bg, config.border)}>
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-2"
      >
        <div className="flex items-center gap-2">
          <Icon className="h-3 w-3 opacity-60" />
          <span className="font-medium">{source.label}</span>
          {source.tokens && (
            <span className="text-slate-500 dark:text-slate-400">
              {formatTokens(source.tokens)} tokens
            </span>
          )}
        </div>
        {isExpanded ? (
          <ChevronUp className="h-3 w-3 opacity-60" />
        ) : (
          <ChevronDown className="h-3 w-3 opacity-60" />
        )}
      </button>
      {isExpanded && (
        <div className="px-2 pb-2 border-t border-current/10">
          <p className="mt-2 text-slate-600 dark:text-slate-400 whitespace-pre-wrap line-clamp-10">
            {source.content}
          </p>
          {source.type === "summary" && source.originalContent && (
            <details className="mt-2">
              <summary className="cursor-pointer text-blue-600 dark:text-blue-400 hover:underline">
                Show original
              </summary>
              <p className="mt-1 p-2 rounded bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 whitespace-pre-wrap">
                {source.originalContent}
              </p>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
