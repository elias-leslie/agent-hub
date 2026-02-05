"use client";

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";

// Loading fallback for charts
function ChartLoadingFallback() {
  return (
    <div className="flex items-center justify-center h-full min-h-[160px] bg-slate-800/30 rounded animate-pulse">
      <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
    </div>
  );
}

// Loading fallback for timeline
function TimelineLoadingFallback() {
  return (
    <div className="flex flex-col h-full p-4 space-y-4">
      <div className="h-10 bg-slate-800/50 rounded animate-pulse" />
      <div className="flex-1 space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-16 bg-slate-800/50 rounded animate-pulse" />
        ))}
      </div>
    </div>
  );
}

// Loading fallback for markdown
function MarkdownLoadingFallback() {
  return (
    <div className="space-y-2 animate-pulse">
      <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-3/4" />
      <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-full" />
      <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-5/6" />
    </div>
  );
}

// Loading fallback for diff view
function DiffViewLoadingFallback() {
  return (
    <div className="rounded-lg overflow-hidden border border-slate-700 bg-slate-900 animate-pulse">
      <div className="h-10 bg-slate-800" />
      <div className="p-4 space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-5 bg-slate-800 rounded" />
        ))}
      </div>
    </div>
  );
}

// Loading fallback for code block
function CodeBlockLoadingFallback() {
  return (
    <div className="rounded-lg overflow-hidden border border-slate-700 bg-slate-900 animate-pulse">
      <div className="h-8 bg-slate-800" />
      <div className="p-4 space-y-1.5">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-4 bg-slate-800 rounded" style={{ width: `${70 + Math.random() * 30}%` }} />
        ))}
      </div>
    </div>
  );
}

// Dynamic imports for heavy components

/**
 * EventTimeline - Heavy component with search, filtering, and event rendering
 */
export const DynamicEventTimeline = dynamic(
  () => import("@/components/timeline/event-timeline").then((mod) => mod.EventTimeline),
  {
    loading: () => <TimelineLoadingFallback />,
    ssr: false,
  }
);

/**
 * MarkdownRenderer - Uses react-markdown and remark-gfm
 */
export const DynamicMarkdownRenderer = dynamic(
  () => import("@/components/output/markdown-renderer").then((mod) => mod.MarkdownRenderer),
  {
    loading: () => <MarkdownLoadingFallback />,
    ssr: false,
  }
);

/**
 * DiffView - Diff parsing and rendering
 */
export const DynamicDiffView = dynamic(
  () => import("@/components/output/diff-view").then((mod) => mod.DiffView),
  {
    loading: () => <DiffViewLoadingFallback />,
    ssr: false,
  }
);

/**
 * CodeBlock - Syntax highlighting with Prism
 */
export const DynamicCodeBlock = dynamic(
  () => import("@/components/output/code-block").then((mod) => mod.CodeBlock),
  {
    loading: () => <CodeBlockLoadingFallback />,
    ssr: false,
  }
);

/**
 * SettingsModal - Large modal with multiple tabs
 */
export const DynamicSettingsModal = dynamic(
  () => import("@/components/settings-modal").then((mod) => mod.SettingsModal),
  {
    loading: () => null,
    ssr: false,
  }
);

/**
 * MemorySettingsModal - Memory configuration modal
 */
export const DynamicMemorySettingsModal = dynamic(
  () => import("@/components/memory/MemorySettingsModal").then((mod) => mod.MemorySettingsModal),
  {
    loading: () => null,
    ssr: false,
  }
);
