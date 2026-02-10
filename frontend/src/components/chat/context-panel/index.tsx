"use client";

import { useState } from "react";
import { PanelRightClose, PanelRightOpen, Database, FileText, MessageSquare } from "lucide-react";
import type { ContextPanelProps } from "./types";
import { TokenBudgetSection } from "./token-budget-section";
import { Section } from "./section";
import { ContextSourceItem } from "./context-source-item";
import { StickyNotesSection } from "./sticky-notes-section";

// Re-export types for backward compatibility
export type {
  ContextSource,
  TokenBudget,
  StickyNote,
  ContextPanelProps,
} from "./types";

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
        <TokenBudgetSection
          tokenBudget={tokenBudget}
          isExpanded={expandedSections.has("budget")}
          onToggle={() => toggleSection("budget")}
        />

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

        <StickyNotesSection
          stickyNotes={stickyNotes}
          onAddNote={onAddNote}
          onRemoveNote={onRemoveNote}
          isExpanded={expandedSections.has("notes")}
          onToggle={() => toggleSection("notes")}
        />
      </div>
    </div>
  );
}
