"use client";

import { useState } from "react";
import type { PreviewBadge } from "./workspace-types";
import type { PersonaIssueMarker } from "@/lib/api/persona-stream";
import { AUTO_FOLLOW_BOTTOM_THRESHOLD } from "./workspace-types";

// --- Formatting ---

export function formatDayLabel(date: Date): string {
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatTimeLabel(date: Date): string {
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatTimestampTitle(date: Date): string {
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatDurationLabel(durationMs: number | null): string | null {
  if (durationMs == null) return null;
  if (durationMs < 1000) return `${durationMs}ms`;
  if (durationMs < 60_000) return `${(durationMs / 1000).toFixed(1)}s`;
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.floor((durationMs % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export function formatRuntimeLabel(seconds: number | null): string | null {
  if (seconds == null) return null;
  if (seconds < 60) return `${seconds}s median`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m median`;
  return `${(seconds / 3600).toFixed(1)}h median`;
}

export function shortenText(value: string, maxLength = 88): string {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1)}\u2026`;
}

// --- Text processing ---

export function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim().toLowerCase();
}

export function unescapeDisplayText(value: string): string {
  return value
    .replace(/\\n/g, "\n")
    .replace(/\\"/g, "\"")
    .replace(/\\'/g, "'")
    .replace(/\\\\/g, "\\");
}

export function extractWrappedTextPayload(value: string): string | null {
  const keyMatch = /['"]text['"]\s*:/.exec(value);
  if (!keyMatch) return null;
  let index = keyMatch.index + keyMatch[0].length;
  while (index < value.length && /\s/.test(value[index])) index += 1;
  const quote = value[index];
  if (quote !== "\"" && quote !== "'") return null;
  index += 1;
  let escaped = false;
  let result = "";
  for (; index < value.length; index += 1) {
    const char = value[index];
    if (escaped) { result += char; escaped = false; continue; }
    if (char === "\\") { result += char; escaped = true; continue; }
    if (char === quote) break;
    result += char;
  }
  const unescaped = unescapeDisplayText(result).trim();
  return unescaped || null;
}

export function humanizeTaskContextText(value: string): string {
  const lines = value.split("\n").map((line) => line.trim()).filter(Boolean);
  if (!lines.some((line) => line.startsWith("TASK:task-"))) return value;

  const prettified: string[] = [];
  for (const line of lines) {
    if (line.startsWith("TASK:")) {
      const [taskId, status, priority, taskType, size] = line.slice(5).split("|");
      prettified.push(`Task ${taskId}${status ? ` \u00b7 ${status}` : ""}${priority ? ` \u00b7 ${priority}` : ""}${taskType ? ` \u00b7 ${taskType}` : ""}${size ? ` \u00b7 ${size}` : ""}`);
      continue;
    }
    if (line.startsWith("TITLE:")) { prettified.push(`Title: ${line.slice(6).trim()}`); continue; }
    if (line.startsWith("DESCRIPTION:")) { prettified.push(`Description: ${line.slice(12).trim()}`); continue; }
    if (line.startsWith("OBJECTIVE:")) { prettified.push(`Description: ${line.slice(10).trim()}`); continue; }
    if (line.startsWith("SPIRIT_ANTI:")) { continue; }  // Removed field
    if (line.startsWith("WORKFLOW:")) { prettified.push(`Workflow: ${line.slice(9).trim().replaceAll("|", " \u00b7 ")}`); continue; }
    if (line.startsWith("CONSTRAINTS")) { continue; }  // Removed field
    if (line.startsWith("DONE_WHEN")) { const [, content = ""] = line.split(":", 2); prettified.push(`Done when: ${content.replaceAll(" | ", "; ").trim()}`); continue; }
    if (line.startsWith("COMPLETE_READY:")) { prettified.push(`Ready gates: ${line.slice(15).trim().replaceAll("|", " \u00b7 ")}`); continue; }
    if (line.startsWith("SYNC_SKIPS:")) { prettified.push(`Sync skips: ${line.slice(11).trim()}`); continue; }
    if (line.startsWith("LANE:")) { prettified.push(`Lane: ${line.slice(5).trim().replaceAll("|", " \u00b7 ")}`); continue; }
    if (line.startsWith("SPECIALISTS:")) { prettified.push(`Specialists: ${line.slice(12).trim().replaceAll("|", " \u00b7 ")}`); continue; }
    if (line.startsWith("DECISIONS[")) { continue; }  // Removed field
    if (/^d\d+:/i.test(line)) { continue; }  // Removed field (decision items)
    if (line.startsWith("SUBTASKS[")) { const [, content = ""] = line.split(":", 2); prettified.push(`Subtasks: ${content.trim()}`); continue; }
    if (/^\d+(\.\d+)?\s+_+/.test(line)) { prettified.push(line.replace(/_+/g, "").replace(/\s+/g, " ").trim()); continue; }
    prettified.push(line);
  }
  return prettified.join("\n");
}

export function prettifyDisplayText(value: string): string {
  const extracted = extractWrappedTextPayload(value);
  const base = extracted ?? value;
  // Strip observability tags — shown separately in narration timeline
  const stripped = base
    .replace(/\[\[P:[a-z_]+:[^\]]*\]?\]?/g, "")
    .replace(/\s*Applied:\s*\[(?:M|G|R):[a-f0-9]{6,8}\]/g, "")
    .replace(/\[\[F:[^\]]*\]?\]?/g, "")
    .replace(/\[\[S:[^\]]*\]?\]?/g, "")
    .replace(/\n{3,}/g, "\n\n");
  return humanizeTaskContextText(unescapeDisplayText(stripped).trim());
}

export function addUniqueText(target: string[], seen: Set<string>, value: string | null | undefined): void {
  if (!value) return;
  const trimmed = value.trim();
  if (!trimmed) return;
  const normalized = normalizeText(trimmed);
  if (seen.has(normalized)) return;
  seen.add(normalized);
  target.push(trimmed);
}

// --- Classification helpers ---

export function eventLabel(eventType: string): string {
  return eventType.replaceAll("_", " ");
}

export function isNearBottom(container: HTMLDivElement): boolean {
  const distanceFromBottom = container.scrollHeight - container.clientHeight - container.scrollTop;
  return distanceFromBottom <= AUTO_FOLLOW_BOTTOM_THRESHOLD;
}

export function eventToneClasses(eventType: string): string {
  if (eventType === "error") return "border-rose-900 bg-rose-950/30 text-rose-300";
  if (eventType === "tool_result") return "border-emerald-900 bg-emerald-950/30 text-emerald-300";
  if (eventType === "tool_use") return "border-sky-900 bg-sky-950/30 text-sky-300";
  if (eventType === "thinking") return "border-fuchsia-900 bg-fuchsia-950/30 text-fuchsia-300";
  return "border-slate-800 bg-slate-950/50 text-slate-300";
}

export function eventSummaryLabel(eventType: string): string {
  if (eventType === "assistant_message") return "Assistant";
  if (eventType === "user_message") return "User";
  if (eventType === "system_message") return "System";
  if (eventType === "tool_use") return "Tool call";
  if (eventType === "tool_result") return "Tool result";
  if (eventType === "error") return "Error";
  if (eventType === "thinking") return "Reasoning";
  return eventLabel(eventType);
}

export function eventAccentClasses(eventType: string): string {
  if (eventType === "error") return "bg-rose-950/40 text-rose-300";
  if (eventType === "tool_result") return "bg-emerald-950/40 text-emerald-300";
  if (eventType === "tool_use") return "bg-sky-950/40 text-sky-300";
  if (eventType === "assistant_message") return "bg-fuchsia-950/40 text-fuchsia-300";
  return "bg-slate-800 text-slate-300";
}

export function badgeToneClasses(tone: PreviewBadge["tone"] = "neutral"): string {
  if (tone === "danger") return "bg-rose-950/40 text-rose-300";
  if (tone === "warning") return "bg-amber-950/40 text-amber-300";
  if (tone === "success") return "bg-emerald-950/40 text-emerald-300";
  if (tone === "info") return "bg-sky-950/40 text-sky-300";
  return "bg-slate-800 text-slate-300";
}

export function entryStatusClasses(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === "failed" || normalized === "error") return "bg-rose-950/40 text-rose-300";
  if (normalized === "completed") return "bg-emerald-950/40 text-emerald-300";
  if (normalized === "active") return "bg-sky-950/40 text-sky-300";
  if (normalized === "paused") return "bg-amber-950/40 text-amber-300";
  return "bg-slate-800 text-slate-300";
}

export function outcomeToneClasses(hasErrors: boolean): string {
  return hasErrors
    ? "bg-rose-950/40 text-rose-300"
    : "bg-emerald-950/40 text-emerald-300";
}

export function rootCauseClasses(rootCause: string): string {
  switch (rootCause) {
    case "workflow": return "bg-fuchsia-950/40 text-fuchsia-300";
    case "tool": return "bg-sky-950/40 text-sky-300";
    case "context": return "bg-amber-950/40 text-amber-300";
    case "infra": return "bg-rose-950/40 text-rose-300";
    case "prompt": return "bg-violet-950/40 text-violet-300";
    default: return "bg-slate-800 text-slate-300";
  }
}

export function compactPath(path: string): string {
  const segments = path.split("/").filter(Boolean);
  if (segments.length <= 3) return path;
  return `.../${segments.slice(-3).join("/")}`;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function humanizeFieldLabel(value: string): string {
  return value.replaceAll(".", " ").replaceAll("_", " ").replace(/\s+/g, " ").trim().replace(/\b\w/g, (char) => char.toUpperCase());
}

export function isPromptLikeText(value: string | null): boolean {
  if (!value) return false;
  const normalized = value.toLowerCase();
  return (
    normalized.includes("# persona safety boundaries")
    || normalized.includes("<persona_context>")
    || normalized.includes("<heartbeat_instructions>")
    || (value.length > 900 && value.split("\n").length > 20)
  );
}

export function isGenericStatusText(value: string | null): boolean {
  if (!value) return false;
  const normalized = normalizeText(value);
  return (
    normalized === "execution completed"
    || normalized === "session started"
    || normalized === "new message"
    || normalized === "tool"
    || normalized.startsWith("waiting for model after")
  );
}

export function shouldRenderPulseSummary(summary: string | null, issueMarkers: PersonaIssueMarker[]): boolean {
  if (!summary) return false;
  if (issueMarkers.length > 0) return false;
  const normalizedSummary = normalizeText(prettifyDisplayText(summary));
  if (!normalizedSummary || isGenericStatusText(normalizedSummary)) return false;
  return !issueMarkers.some((marker) => {
    const markerText = normalizeText(prettifyDisplayText(`${marker.title}\n${marker.detail ?? marker.summary}`));
    return markerText === normalizedSummary || markerText.includes(normalizedSummary) || normalizedSummary.includes(markerText);
  });
}

// --- Heartbeat classification ---

export function heartbeatIsImportant(entry: { summary_oneliner?: string | null; live_summary?: string | null }): boolean {
  const summary = `${entry.summary_oneliner ?? ""} ${entry.live_summary ?? ""}`.toLowerCase();
  const importantKeywords = [
    "dispatch", "publish", "verified", "verify", "fixed", "created ",
    "reconciled", "merged", "review", "audit", "error", "failed",
    "blocked", "warning", "assess", "investig", "task-",
  ];
  return importantKeywords.some((keyword) => summary.includes(keyword));
}

// --- Small UI components ---

export function DateDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-3">
      <div className="h-px flex-1 bg-slate-800" />
      <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-slate-600">
        {label}
      </span>
      <div className="h-px flex-1 bg-slate-800" />
    </div>
  );
}

export function TimelineTimestamp({ timestamp }: { timestamp: Date }) {
  const label = formatTimeLabel(timestamp);
  const title = formatTimestampTitle(timestamp);
  return (
    <time
      dateTime={timestamp.toISOString()}
      title={title}
      className="shrink-0 pt-2 text-[10px] font-medium tabular-nums tracking-[0.08em] text-slate-500"
    >
      {label}
    </time>
  );
}

function highlightKeywordClass(token: string): string {
  const normalized = token.toLowerCase();
  if (["error", "failed", "failure", "blocked"].includes(normalized))
    return "rounded-md bg-rose-950/40 px-1 py-0.5 text-rose-300";
  if (["warning", "warn", "paused"].includes(normalized))
    return "rounded-md bg-amber-950/40 px-1 py-0.5 text-amber-300";
  if (["success", "succeeded", "completed", "ok"].includes(normalized))
    return "rounded-md bg-emerald-950/40 px-1 py-0.5 text-emerald-300";
  if (["running", "working", "active"].includes(normalized))
    return "rounded-md bg-sky-950/40 px-1 py-0.5 text-sky-300";
  return "";
}

export function HighlightedText({ text, className }: { text: string; className?: string }) {
  const parts = text.split(/(\b(?:error|failed|failure|warning|warn|success|succeeded|completed|ok|running|working|active|blocked|paused)\b)/gi);
  return (
    <span className={className}>
      {parts.map((part, index) => {
        const kc = highlightKeywordClass(part);
        return kc
          ? <span key={`${part}-${index}`} className={kc}>{part}</span>
          : <span key={`${part}-${index}`}>{part}</span>;
      })}
    </span>
  );
}

export function ExpandableText({
  text,
  expandedText,
  className,
  collapsedLength = 180,
}: {
  text: string;
  expandedText?: string | null;
  className?: string;
  collapsedLength?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const collapsedText = prettifyDisplayText(text);
  const fullText = prettifyDisplayText(expandedText && expandedText.trim().length > 0 ? expandedText : text);
  const shouldCollapse = fullText.length > collapsedLength || fullText !== collapsedText;

  if (!shouldCollapse) return <HighlightedText text={fullText} className={className} />;

  return (
    <div>
      <HighlightedText
        text={expanded ? fullText : shortenText(collapsedText, collapsedLength)}
        className={className}
      />
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        className="mt-1 inline-flex items-center rounded-full border border-slate-700 px-2 py-0.5 text-[10px] font-medium text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
      >
        {expanded ? "Less" : "More"}
      </button>
    </div>
  );
}
