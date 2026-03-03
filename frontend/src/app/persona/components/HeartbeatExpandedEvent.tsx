"use client";

import { useState } from "react";
import {
  ChevronRight,
  Wrench,
  Brain,
  MessageSquare,
  AlertCircle,
  Clock,
  CornerDownRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "@agent-hub/chat-ui";
import {
  SessionEvent,
  CATEGORY_STYLES,
  getToolCategory,
} from "./HeartbeatSessionCardTypes";

/* ── CollapsibleText ──────────────────────────────── */

function CollapsibleText({
  content,
  maxLength = 300,
  className,
}: {
  content: string;
  maxLength?: number;
  className?: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const needsTruncation = content.length > maxLength;
  const display = isOpen ? content : content.slice(0, maxLength);

  return (
    <div>
      <span className={cn("whitespace-pre-wrap break-all", className)}>
        {display}
        {needsTruncation && !isOpen && "\u2026"}
      </span>
      {needsTruncation && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            setIsOpen(!isOpen);
          }}
          className="ml-1 text-[9px] text-amber-500/70 hover:text-amber-400"
        >
          {isOpen ? "\u25be less" : "\u25b8 more"}
        </button>
      )}
    </div>
  );
}

/* ── DurationBadge ────────────────────────────────── */

function DurationBadge({ ms }: { ms: number }) {
  const label = ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
  return (
    <span className="inline-flex items-center gap-0.5 text-[9px] font-mono text-slate-500">
      <Clock className="w-2.5 h-2.5" />
      {label}
    </span>
  );
}

/* ── ExpandedEvent (timeline-style) ──────────────── */

export function ExpandedEvent({ event }: { event: SessionEvent }) {
  /* ─── Thinking — expanded by default ─── */
  if (event.event_type === "thinking") {
    const [open, setOpen] = useState(true);
    const wordCount = event.content ? event.content.split(/\s+/).length : 0;
    return (
      <div className="relative pl-5 py-1">
        <div className="absolute left-0 top-[10px] w-2 h-2 rounded-full ring-2 bg-violet-400 ring-violet-500/20" />
        <div className="absolute left-[3px] top-[18px] bottom-0 w-px bg-slate-700/20" />

        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 w-full text-left"
        >
          <Brain className="w-3 h-3 text-violet-400 flex-shrink-0" />
          <span className="text-[10px] font-medium text-violet-400">
            Thinking
          </span>
          <ChevronRight
            className={cn(
              "w-2.5 h-2.5 text-violet-400/40 transition-transform duration-150",
              open && "rotate-90",
            )}
          />
          <span className="ml-auto flex items-center gap-2 text-[9px] text-slate-500">
            {wordCount > 0 && <span>{wordCount} words</span>}
            {event.tokens != null && (
              <span className="font-mono">{event.tokens}t</span>
            )}
          </span>
        </button>
        {open && event.content && (
          <div className="mt-1.5 ml-5 rounded-md bg-gradient-to-br from-violet-500/5 to-transparent border border-violet-500/10 p-2.5">
            <p className="text-[11px] text-slate-400 whitespace-pre-wrap leading-relaxed">
              {event.content}
            </p>
          </div>
        )}
      </div>
    );
  }

  /* ─── Tool Use — collapsed by default ─── */
  if (event.event_type === "tool_use") {
    const [open, setOpen] = useState(false);
    const input = event.tool_input as Record<string, unknown> | null;
    const isBash = event.tool_name === "Bash";
    const description =
      isBash && input?.description ? String(input.description) : null;
    const command = isBash && input?.command ? String(input.command) : null;
    const category = getToolCategory(event.tool_name);
    const catStyle = CATEGORY_STYLES[category];

    return (
      <div className="relative pl-5 py-1">
        <div
          className={cn(
            "absolute left-0 top-[10px] w-2 h-2 rounded-full ring-2",
            catStyle.dot,
          )}
        />
        <div className="absolute left-[3px] top-[18px] bottom-0 w-px bg-slate-700/20" />

        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 flex-wrap w-full text-left"
        >
          <Wrench className="w-3 h-3 text-amber-500 flex-shrink-0" />
          <span
            className={cn(
              "text-[9px] font-bold font-mono uppercase tracking-wider px-1.5 py-0.5 rounded border",
              catStyle.badge,
            )}
          >
            {category !== "default" ? category : "tool"}
          </span>
          <span className="text-[10px] font-semibold font-mono text-slate-300">
            {event.tool_name || "tool"}
          </span>
          {description && (
            <span className="text-[9px] text-slate-500 italic truncate max-w-[200px]">
              {description}
            </span>
          )}
          <span className="ml-auto flex items-center gap-2 flex-shrink-0">
            {event.duration_ms != null && (
              <DurationBadge ms={event.duration_ms} />
            )}
            <ChevronRight
              className={cn(
                "w-2.5 h-2.5 text-slate-600 transition-transform duration-150",
                open && "rotate-90",
              )}
            />
          </span>
        </button>

        {open && (
          <div className="mt-1.5 ml-5 space-y-1">
            {command ? (
              <CollapsibleText
                content={command}
                maxLength={400}
                className="text-[10px] text-slate-500 font-mono"
              />
            ) : input ? (
              <CollapsibleText
                content={JSON.stringify(input, null, 2)}
                maxLength={400}
                className="text-[10px] text-slate-500 font-mono"
              />
            ) : null}
          </div>
        )}
      </div>
    );
  }

  /* ─── Tool Result — collapsed by default ─── */
  if (event.event_type === "tool_result") {
    const [open, setOpen] = useState(false);
    const resultContent =
      event.content ||
      (event.tool_output as Record<string, unknown>)?.content?.toString() ||
      "";
    if (!resultContent) return null;

    const previewLen = Math.min(resultContent.length, 60);
    const preview = resultContent.slice(0, previewLen).replace(/\n/g, " ");

    return (
      <div className="relative pl-5 py-0.5">
        <div className="absolute left-[2px] top-[8px] w-1 h-1 rounded-full bg-slate-600" />
        <div className="absolute left-[3px] top-[12px] bottom-0 w-px bg-slate-700/20" />

        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 w-full text-left group"
        >
          <CornerDownRight className="w-2.5 h-2.5 text-slate-600 flex-shrink-0" />
          <span className="text-[9px] font-mono text-slate-600 truncate flex-1">
            {open ? "result" : preview}
            {!open && resultContent.length > previewLen && "\u2026"}
          </span>
          <ChevronRight
            className={cn(
              "w-2.5 h-2.5 text-slate-700 transition-transform duration-150 opacity-0 group-hover:opacity-100",
              open && "rotate-90 opacity-100",
            )}
          />
        </button>

        {open && (
          <div className="ml-5 mt-1 rounded bg-slate-800/40 border border-slate-700/30 px-2 py-1.5">
            <CollapsibleText
              content={resultContent}
              maxLength={500}
              className="text-[9px] text-slate-500 font-mono"
            />
          </div>
        )}
      </div>
    );
  }

  /* ─── Assistant Message — expanded by default ─── */
  if (event.event_type === "assistant_message") {
    return (
      <div className="relative pl-5 py-1">
        <div className="absolute left-0 top-[10px] w-2 h-2 rounded-full ring-2 bg-sky-400 ring-sky-500/20" />
        <div className="absolute left-[3px] top-[18px] bottom-0 w-px bg-slate-700/20" />

        <div className="flex items-center gap-2 mb-1">
          <MessageSquare className="w-3 h-3 text-sky-400 flex-shrink-0" />
          <span className="text-[10px] font-medium text-sky-400">
            Response
          </span>
        </div>
        {event.content && (
          <div className="ml-5">
            <MarkdownContent
              content={event.content}
              className="text-[11px] leading-relaxed [&_p]:my-0.5 [&_code]:text-[10px]"
            />
          </div>
        )}
      </div>
    );
  }

  /* ─── Error — always expanded ─── */
  if (event.event_type === "error") {
    return (
      <div className="relative pl-5 py-1">
        <div className="absolute left-0 top-[10px] w-2 h-2 rounded-full ring-2 bg-red-400 ring-red-500/20" />
        <div className="absolute left-[3px] top-[18px] bottom-0 w-px bg-slate-700/20" />

        <div className="flex items-start gap-2">
          <AlertCircle className="w-3 h-3 text-red-400 mt-0.5 flex-shrink-0" />
          <p className="text-[11px] text-red-400 font-mono break-words whitespace-pre-wrap">
            {event.content}
          </p>
        </div>
      </div>
    );
  }

  /* ─── Fallback ─── */
  if (event.content) {
    return (
      <div className="relative pl-5 py-0.5">
        <div className="absolute left-[2px] top-[6px] w-1 h-1 rounded-full bg-slate-600" />
        <div className="absolute left-[3px] top-[10px] bottom-0 w-px bg-slate-700/20" />
        <span className="text-[10px] text-slate-500 break-words">
          {event.event_type}: {event.content}
        </span>
      </div>
    );
  }

  return null;
}
