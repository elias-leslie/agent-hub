"use client";

import {
  useCallback,
  useDeferredValue,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  startTransition,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Search,
  Loader2,
  HeartPulse,
  Wrench,
  Bot,
  Sparkles,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  ArrowDown,
  ArrowUp,
  Clock3,
  Radio,
  CircleDot,
} from "lucide-react";
import {
  MessageBubble,
  MessageInput,
  useChatStream,
  type ChatMessage,
} from "@agent-hub/chat-ui";

import { SessionDropdown } from "@/components/chat/session-dropdown";
import { useSessionEvents } from "@/hooks/use-session-events";
import { cn } from "@/lib/utils";
import { INTERNAL_HEADERS, fetchApi, getApiBaseUrl, getSseBaseUrl, getWsUrl } from "@/lib/api-config";
import { fetchSessionEvents } from "@/lib/api/sessions";
import {
  type PersonaStreamMatch,
  type PersonaIssueMarker,
  type PersonaPulseSummary,
  fetchPersonaStream,
  type PersonaStreamEventPreview,
  type PersonaStreamEntry,
} from "@/lib/api/persona-stream";
import type { SessionEvent as LiveSessionEvent, TimelineEvent } from "@/types/events";
import { TimeRangeDropdown, type TimeRange } from "./TimeRangeDropdown";
import {
  entryHasPulseTag,
  filterIssueMarkers,
  filterModeToPulseTag,
  type FilterMode,
  visibleIssueMarkers,
  pulseTagToFilterMode,
  pulseTagClasses,
  pulseTagLabel,
  rootCauseLabel,
} from "./pulse-helpers";

const PROJECT_ID = "persona-sandbox";
const PAGE_SIZE = 120;
const LIVE_REFRESH_MS = 5_000;
const AUTO_FOLLOW_BOTTOM_THRESHOLD = 160;
const PROGRAMMATIC_SCROLL_GRACE_MS = 400;

interface UnifiedPersonaWorkspaceProps {
  agentSlug: string;
  activeSessionId: string | null;
  sidebarRefreshTrigger: number;
  runtimeSyncKey: string;
  onSelectSession: (sessionId: string | null) => void;
  onSessionCreated: (sessionId: string) => void;
  onNewSession: () => void;
}

type FeedMessage = { kind: "message"; id: string; sessionId: string | null; timestamp: Date; message: ChatMessage };
type FeedHeartbeat = {
  kind: "heartbeat";
  id: string;
  sessionId: string;
  timestamp: Date;
  entry: PersonaStreamEntry;
};
type FeedChildRun = {
  kind: "child_run";
  id: string;
  sessionId: string;
  timestamp: Date;
  entry: PersonaStreamEntry;
};
type FeedAnchor = FeedMessage | FeedHeartbeat | FeedChildRun;
type FeedItem = FeedAnchor;

interface ItemTimelineBlock {
  kind: "item";
  anchorItem: FeedAnchor;
  childRuns: FeedChildRun[];
}

interface RoutineHeartbeatTimelineBlock {
  kind: "routine_group";
  id: string;
  items: Array<{
    anchorItem: FeedHeartbeat;
    childRuns: FeedChildRun[];
  }>;
}

type TimelineBlock = ItemTimelineBlock | RoutineHeartbeatTimelineBlock;

interface LiveSessionPatch {
  liveSummary: string | null;
  liveStatus: string | null;
  eventPreviews: PersonaStreamEventPreview[];
}

interface PreviewBadge {
  label: string;
  tone?: "neutral" | "info" | "success" | "warning" | "danger";
}

interface SessionEventDetailsState {
  loading: boolean;
  error: string | null;
  events: TimelineEvent[];
}

interface DetailField {
  label: string;
  value: string;
  tone?: "neutral" | "info" | "success" | "warning" | "danger";
}

interface SessionDetailBlock {
  id: string;
  timestamp: string;
  eventType: string;
  label: string;
  title: string | null;
  lead: string | null;
  textBlocks: string[];
  fields: DetailField[];
  score: number;
  defaultVisible: boolean;
}

const EMPTY_PULSE: PersonaPulseSummary = {
  metrics: [],
  issue_groups: [],
  agent_scorecards: [],
};

type TimelineRow =
  | { kind: "divider"; id: string; label: string }
  | { kind: "unread"; id: string }
  | { kind: "routine_group"; id: string; block: RoutineHeartbeatTimelineBlock }
  | { kind: "item"; id: string; item: FeedAnchor; childRuns: FeedChildRun[] };

function isChildRunItem(item: FeedItem): item is FeedChildRun {
  return item.kind === "child_run";
}

function canAnchorChildRuns(item: FeedAnchor): item is FeedMessage | FeedHeartbeat {
  return item.kind !== "child_run";
}

function buildChatMessage(entry: PersonaStreamEntry): ChatMessage {
  return {
    id: entry.id,
    role: (entry.role as ChatMessage["role"]) || "assistant",
    content: entry.content || "",
    timestamp: new Date(entry.timestamp),
    agentName: entry.agent_slug || undefined,
    agentModel: entry.model || undefined,
    agentProvider: "claude",
  };
}

function buildLocalFeedMessages(messages: ChatMessage[], currentSessionId: string | null): FeedItem[] {
  return messages.map((message) => ({
    kind: "message" as const,
    id: message.id,
    sessionId: currentSessionId,
    timestamp: message.timestamp,
    message,
  }));
}

function buildRemoteFeedItems(entries: PersonaStreamEntry[]): FeedItem[] {
  return entries.map((entry) => {
    if (entry.entry_type === "message") {
      return {
        kind: "message" as const,
        id: entry.id,
        sessionId: entry.session_id,
        timestamp: new Date(entry.timestamp),
        message: buildChatMessage(entry),
      };
    }
    return {
      kind: entry.entry_type,
      id: entry.id,
      sessionId: entry.session_id,
      timestamp: new Date(entry.timestamp),
      entry,
    };
  });
}

function DateDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-4">
      <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
      <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
        {label}
      </span>
      <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
    </div>
  );
}

function formatDayLabel(date: Date): string {
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatTimeLabel(date: Date): string {
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatTimestampTitle(date: Date): string {
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function TimelineTimestamp({ timestamp }: { timestamp: Date }) {
  const label = formatTimeLabel(timestamp);
  const title = formatTimestampTitle(timestamp);

  return (
    <time
      dateTime={timestamp.toISOString()}
      title={title}
      className="shrink-0 pt-2 text-[11px] font-medium tabular-nums tracking-[0.08em] text-slate-400 dark:text-slate-500"
    >
      {label}
    </time>
  );
}

function formatDurationLabel(durationMs: number | null): string | null {
  if (durationMs == null) {
    return null;
  }
  if (durationMs < 1000) {
    return `${durationMs}ms`;
  }
  if (durationMs < 60_000) {
    return `${(durationMs / 1000).toFixed(1)}s`;
  }
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.floor((durationMs % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function shortenText(value: string, maxLength = 88): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1)}…`;
}

function highlightKeywordClass(token: string): string {
  const normalized = token.toLowerCase();
  if (["error", "failed", "failure", "blocked"].includes(normalized)) {
    return "rounded-md bg-rose-100 px-1 py-0.5 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300";
  }
  if (["warning", "warn", "paused"].includes(normalized)) {
    return "rounded-md bg-amber-100 px-1 py-0.5 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300";
  }
  if (["success", "succeeded", "completed", "ok"].includes(normalized)) {
    return "rounded-md bg-emerald-100 px-1 py-0.5 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300";
  }
  if (["running", "working", "active"].includes(normalized)) {
    return "rounded-md bg-sky-100 px-1 py-0.5 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300";
  }
  return "";
}

function HighlightedText({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const parts = text.split(/(\b(?:error|failed|failure|warning|warn|success|succeeded|completed|ok|running|working|active|blocked|paused)\b)/gi);

  return (
    <span className={className}>
      {parts.map((part, index) => {
        const keywordClass = highlightKeywordClass(part);
        if (!keywordClass) {
          return <span key={`${part}-${index}`}>{part}</span>;
        }
        return (
          <span key={`${part}-${index}`} className={keywordClass}>
            {part}
          </span>
        );
      })}
    </span>
  );
}

function ExpandableText({
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

  if (!shouldCollapse) {
    return <HighlightedText text={fullText} className={className} />;
  }

  return (
    <div>
      <HighlightedText
        text={expanded ? fullText : shortenText(collapsedText, collapsedLength)}
        className={className}
      />
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        className="mt-1 inline-flex items-center rounded-full border border-slate-200 px-2.5 py-0.5 text-[11px] font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
      >
        {expanded ? "Less" : "More"}
      </button>
    </div>
  );
}

function eventLabel(eventType: string): string {
  return eventType.replaceAll("_", " ");
}

function isNearBottom(container: HTMLDivElement): boolean {
  const distanceFromBottom = container.scrollHeight - container.clientHeight - container.scrollTop;
  return distanceFromBottom <= AUTO_FOLLOW_BOTTOM_THRESHOLD;
}

function eventToneClasses(eventType: string): string {
  if (eventType === "error") {
    return "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300";
  }
  if (eventType === "tool_result") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300";
  }
  if (eventType === "tool_use") {
    return "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950/30 dark:text-sky-300";
  }
  if (eventType === "thinking") {
    return "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700 dark:border-fuchsia-900 dark:bg-fuchsia-950/30 dark:text-fuchsia-300";
  }
  return "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-950/50 dark:text-slate-300";
}

function eventSummaryLabel(eventType: string): string {
  if (eventType === "assistant_message") {
    return "Assistant";
  }
  if (eventType === "user_message") {
    return "User";
  }
  if (eventType === "system_message") {
    return "System";
  }
  if (eventType === "tool_use") {
    return "Tool call";
  }
  if (eventType === "tool_result") {
    return "Tool result";
  }
  if (eventType === "error") {
    return "Error";
  }
  if (eventType === "thinking") {
    return "Reasoning";
  }
  return eventLabel(eventType);
}

function eventAccentClasses(eventType: string): string {
  if (eventType === "error") {
    return "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300";
  }
  if (eventType === "tool_result") {
    return "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300";
  }
  if (eventType === "tool_use") {
    return "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300";
  }
  if (eventType === "assistant_message") {
    return "bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-950/40 dark:text-fuchsia-300";
  }
  return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";
}

function badgeToneClasses(tone: PreviewBadge["tone"] = "neutral"): string {
  if (tone === "danger") {
    return "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300";
  }
  if (tone === "warning") {
    return "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300";
  }
  if (tone === "success") {
    return "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300";
  }
  if (tone === "info") {
    return "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300";
  }
  return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";
}

function compactPath(path: string): string {
  const segments = path.split("/").filter(Boolean);
  if (segments.length <= 3) {
    return path;
  }
  return `.../${segments.slice(-3).join("/")}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function humanizeFieldLabel(value: string): string {
  return value
    .replaceAll(".", " ")
    .replaceAll("_", " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim().toLowerCase();
}

function unescapeDisplayText(value: string): string {
  return value
    .replace(/\\n/g, "\n")
    .replace(/\\"/g, "\"")
    .replace(/\\'/g, "'")
    .replace(/\\\\/g, "\\");
}

function extractWrappedTextPayload(value: string): string | null {
  const keyMatch = /['"]text['"]\s*:/.exec(value);
  if (!keyMatch) {
    return null;
  }
  let index = keyMatch.index + keyMatch[0].length;
  while (index < value.length && /\s/.test(value[index])) {
    index += 1;
  }
  const quote = value[index];
  if (quote !== "\"" && quote !== "'") {
    return null;
  }
  index += 1;
  let escaped = false;
  let result = "";
  for (; index < value.length; index += 1) {
    const char = value[index];
    if (escaped) {
      result += char;
      escaped = false;
      continue;
    }
    if (char === "\\") {
      result += char;
      escaped = true;
      continue;
    }
    if (char === quote) {
      break;
    }
    result += char;
  }
  const unescaped = unescapeDisplayText(result).trim();
  return unescaped || null;
}

function humanizeTaskContextText(value: string): string {
  const lines = value.split("\n").map((line) => line.trim()).filter(Boolean);
  if (!lines.some((line) => line.startsWith("TASK:task-"))) {
    return value;
  }

  const prettified: string[] = [];
  for (const line of lines) {
    if (line.startsWith("TASK:")) {
      const [taskId, status, priority, taskType, size] = line.slice(5).split("|");
      prettified.push(
        `Task ${taskId}${status ? ` · ${status}` : ""}${priority ? ` · ${priority}` : ""}${taskType ? ` · ${taskType}` : ""}${size ? ` · ${size}` : ""}`,
      );
      continue;
    }
    if (line.startsWith("TITLE:")) {
      prettified.push(`Title: ${line.slice(6).trim()}`);
      continue;
    }
    if (line.startsWith("DESCRIPTION:")) {
      prettified.push(`Description: ${line.slice(12).trim()}`);
      continue;
    }
    if (line.startsWith("OBJECTIVE:")) {
      prettified.push(`Objective: ${line.slice(10).trim()}`);
      continue;
    }
    if (line.startsWith("SPIRIT_ANTI:")) {
      prettified.push(`Avoid: ${line.slice(12).trim()}`);
      continue;
    }
    if (line.startsWith("WORKFLOW:")) {
      prettified.push(`Workflow: ${line.slice(9).trim().replaceAll("|", " · ")}`);
      continue;
    }
    if (line.startsWith("CONSTRAINTS")) {
      const [, content = ""] = line.split(":", 2);
      prettified.push(`Constraints: ${content.replaceAll(" | ", "; ").trim()}`);
      continue;
    }
    if (line.startsWith("DONE_WHEN")) {
      const [, content = ""] = line.split(":", 2);
      prettified.push(`Done when: ${content.replaceAll(" | ", "; ").trim()}`);
      continue;
    }
    if (line.startsWith("COMPLETE_READY:")) {
      prettified.push(`Ready gates: ${line.slice(15).trim().replaceAll("|", " · ")}`);
      continue;
    }
    if (line.startsWith("SYNC_SKIPS:")) {
      prettified.push(`Sync skips: ${line.slice(11).trim()}`);
      continue;
    }
    if (line.startsWith("LANE:")) {
      prettified.push(`Lane: ${line.slice(5).trim().replaceAll("|", " · ")}`);
      continue;
    }
    if (line.startsWith("SPECIALISTS:")) {
      prettified.push(`Specialists: ${line.slice(12).trim().replaceAll("|", " · ")}`);
      continue;
    }
    if (line.startsWith("DECISIONS[")) {
      prettified.push("Decisions:");
      continue;
    }
    if (/^d\d+:/i.test(line)) {
      prettified.push(`- ${line.replace(/^d\d+:/i, "").replace("→", " -> ").trim()}`);
      continue;
    }
    if (line.startsWith("SUBTASKS[")) {
      const [, content = ""] = line.split(":", 2);
      prettified.push(`Subtasks: ${content.trim()}`);
      continue;
    }
    if (/^\d+(\.\d+)?\s+_+/.test(line)) {
      prettified.push(line.replace(/_+/g, "").replace(/\s+/g, " ").trim());
      continue;
    }
    prettified.push(line);
  }

  return prettified.join("\n");
}

function prettifyDisplayText(value: string): string {
  const extracted = extractWrappedTextPayload(value);
  const base = extracted ?? value;
  return humanizeTaskContextText(unescapeDisplayText(base).trim());
}

function addUniqueText(target: string[], seen: Set<string>, value: string | null | undefined): void {
  if (!value) {
    return;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return;
  }
  const normalized = normalizeText(trimmed);
  if (seen.has(normalized)) {
    return;
  }
  seen.add(normalized);
  target.push(trimmed);
}

function describeValue(value: unknown): string | null {
  if (value == null) {
    return null;
  }
  if (typeof value === "string") {
    const prettified = prettifyDisplayText(value);
    return prettified || null;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    const items = value
      .map((item) => describeValue(item))
      .filter((item): item is string => Boolean(item));
    return items.length > 0 ? items.join(", ") : null;
  }
  return null;
}

function flattenReadableFields(
  value: unknown,
  parentKey = "",
  depth = 0,
): DetailField[] {
  if (depth > 3 || value == null) {
    return [];
  }
  if (Array.isArray(value)) {
    if (value.every((item) => !isRecord(item) && !Array.isArray(item))) {
      const described = describeValue(value);
      return described && parentKey ? [{ label: humanizeFieldLabel(parentKey), value: described }] : [];
    }
    return value.flatMap((item, index) =>
      flattenReadableFields(item, parentKey ? `${parentKey}.${index + 1}` : String(index + 1), depth + 1),
    );
  }
  if (!isRecord(value)) {
    const described = describeValue(value);
    return described && parentKey ? [{ label: humanizeFieldLabel(parentKey), value: described }] : [];
  }

  const preferredOrder = [
    "command",
    "action",
    "description",
    "path",
    "file_path",
    "target_file",
    "task_id",
    "project",
    "project_id",
    "status",
    "exit_code",
    "current_branch",
    "branch",
    "files_touched",
    "changed_files",
  ];
  const entries = Object.entries(value).sort(([left], [right]) => {
    const leftIndex = preferredOrder.indexOf(left);
    const rightIndex = preferredOrder.indexOf(right);
    if (leftIndex === -1 && rightIndex === -1) {
      return left.localeCompare(right);
    }
    if (leftIndex === -1) {
      return 1;
    }
    if (rightIndex === -1) {
      return -1;
    }
    return leftIndex - rightIndex;
  });

  return entries.flatMap(([key, nestedValue]) =>
    flattenReadableFields(nestedValue, parentKey ? `${parentKey}.${key}` : key, depth + 1),
  );
}

function fieldTone(label: string, value: string): DetailField["tone"] {
  const normalizedValue = value.toLowerCase();
  const normalizedLabel = label.toLowerCase();
  if (normalizedLabel.includes("status")) {
    if (["ok", "success", "succeeded", "completed"].includes(normalizedValue)) {
      return "success";
    }
    if (["failed", "error", "blocked"].includes(normalizedValue)) {
      return "danger";
    }
  }
  if (normalizedLabel.includes("exit code")) {
    return normalizedValue === "0" ? "success" : "danger";
  }
  if (normalizedValue === "true" && normalizedLabel.includes("error")) {
    return "danger";
  }
  if (normalizedLabel.includes("file") || normalizedLabel.includes("path")) {
    return "info";
  }
  if (normalizedLabel.includes("task")) {
    return "warning";
  }
  return "neutral";
}

function buildEventDetails(event: TimelineEvent): {
  lead: string | null;
  textBlocks: string[];
  fields: DetailField[];
} {
  const textBlocks: string[] = [];
  const textSeen = new Set<string>();
  const fields: DetailField[] = [];
  const fieldSeen = new Set<string>();

  const addField = (label: string, value: string | null | undefined, tone?: DetailField["tone"]) => {
    if (!value) {
      return;
    }
    const trimmed = value.trim();
    if (!trimmed) {
      return;
    }
    const fieldKey = `${label}:${normalizeText(trimmed)}`;
    if (fieldSeen.has(fieldKey)) {
      return;
    }
    fieldSeen.add(fieldKey);
    fields.push({
      label,
      value: trimmed,
      tone: tone ?? fieldTone(label, trimmed),
    });
  };

  const recordTextFields = (value: Record<string, unknown> | null, keys: string[]) => {
    if (!value) {
      return;
    }
    for (const key of keys) {
      addUniqueText(textBlocks, textSeen, describeValue(value[key]));
    }
  };

  const filterFields = (
    source: Record<string, unknown> | null,
    excludedKeys: string[],
  ) => {
    if (!source) {
      return;
    }
    const exclusions = new Set(excludedKeys);
    for (const field of flattenReadableFields(source)) {
      const normalizedLabel = field.label.toLowerCase().replaceAll(" ", "_");
      if ([...exclusions].some((key) => normalizedLabel.endsWith(key))) {
        continue;
      }
      const value = field.label.toLowerCase().includes("file") || field.label.toLowerCase().includes("path")
        ? compactPath(field.value)
        : field.value;
      addField(field.label, value, field.tone);
    }
  };

  if (event.event_type === "tool_use") {
    const toolInput = isRecord(event.tool_input) ? event.tool_input : null;
    addField("Command", describeValue(toolInput?.command), "info");
    addField("Action", describeValue(toolInput?.action));
    addField("Description", describeValue(toolInput?.description));
    addField("File", describeValue(toolInput?.file_path ?? toolInput?.path ?? toolInput?.target_file), "info");
    addField("Task", describeValue(toolInput?.task_id), "warning");
    addField("Project", describeValue(toolInput?.project ?? toolInput?.project_id));
    filterFields(toolInput, ["command", "action", "description", "file_path", "path", "target_file", "task_id", "project", "project_id"]);
  } else if (event.event_type === "tool_result") {
    const toolOutput = isRecord(event.tool_output) ? event.tool_output : null;
    recordTextFields(toolOutput, ["content", "summary", "stdout", "stderr", "error_message", "message"]);
    addField("Status", describeValue(toolOutput?.status));
    addField("Exit code", describeValue(toolOutput?.exit_code));
    addField("Error", describeValue(toolOutput?.is_error));
    addField("Task", describeValue(toolOutput?.task_id), "warning");
    addField("File", describeValue(toolOutput?.file_path ?? toolOutput?.path ?? toolOutput?.target_file), "info");
    addField("Files touched", describeValue(toolOutput?.files_touched ?? toolOutput?.changed_files), "info");
    filterFields(toolOutput, ["content", "summary", "stdout", "stderr", "error_message", "message", "status", "exit_code", "is_error", "task_id", "file_path", "path", "target_file", "files_touched", "changed_files"]);
  } else {
    addUniqueText(textBlocks, textSeen, event.content);
  }

  if (event.duration_ms != null) {
    addField("Duration", formatDurationLabel(event.duration_ms));
  }
  if (event.model_used) {
    addField("Model", event.model_used);
  }

  const lead = textBlocks[0] ?? fields[0]?.value ?? null;
  return {
    lead,
    textBlocks,
    fields,
  };
}

function dedupeDetailFields(fields: DetailField[]): DetailField[] {
  const seen = new Set<string>();
  return fields.filter((field) => {
    const key = `${field.label}:${normalizeText(field.value)}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function dedupeTextBlocks(values: string[]): string[] {
  const deduped: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    addUniqueText(deduped, seen, value);
  }
  return deduped;
}

function isPromptLikeText(value: string | null): boolean {
  if (!value) {
    return false;
  }
  const normalized = value.toLowerCase();
  return (
    normalized.includes("# persona safety boundaries")
    || normalized.includes("<persona_context>")
    || normalized.includes("<heartbeat_instructions>")
    || (value.length > 900 && value.split("\n").length > 20)
  );
}

function isGenericStatusText(value: string | null): boolean {
  if (!value) {
    return false;
  }
  const normalized = normalizeText(value);
  return (
    normalized === "execution completed"
    || normalized === "session started"
    || normalized === "new message"
    || normalized === "tool"
    || normalized.startsWith("waiting for model after")
  );
}

function shouldRenderPulseSummary(summary: string | null, issueMarkers: PersonaIssueMarker[]): boolean {
  if (!summary) {
    return false;
  }
  const normalizedSummary = normalizeText(prettifyDisplayText(summary));
  if (!normalizedSummary || isGenericStatusText(normalizedSummary)) {
    return false;
  }
  return !issueMarkers.some((marker) => {
    const markerText = normalizeText(prettifyDisplayText(`${marker.title}\n${marker.detail ?? marker.summary}`));
    return (
      markerText === normalizedSummary
      || markerText.includes(normalizedSummary)
      || normalizedSummary.includes(markerText)
    );
  });
}

function eventImportanceScore(event: TimelineEvent, details: ReturnType<typeof buildEventDetails>): number {
  const combinedText = [details.lead, ...details.textBlocks].join(" ").toLowerCase();
  const fieldText = details.fields.map((field) => `${field.label} ${field.value}`).join(" ").toLowerCase();

  if (event.event_type === "error") {
    return 100;
  }
  if (event.event_type === "memory_inject" || event.event_type === "memory_cite") {
    return 0;
  }
  if ((event.event_type === "system_message" || event.role === "system") && isPromptLikeText(event.content)) {
    return 0;
  }
  if (event.event_type === "thinking") {
    return combinedText.includes("error") || combinedText.includes("blocked") ? 40 : 5;
  }
  if (event.event_type === "tool_result") {
    const hasFailureSignal =
      combinedText.includes("error")
      || combinedText.includes("failed")
      || fieldText.includes("exit code 1")
      || fieldText.includes("status failed")
      || fieldText.includes("error true");
    if (hasFailureSignal) {
      return 95;
    }
    const hasStrongOutcome =
      combinedText.includes("publish")
      || combinedText.includes("commit")
      || combinedText.includes("verified")
      || combinedText.includes("merged")
      || combinedText.includes("completed")
      || combinedText.includes("passed")
      || fieldText.includes("task")
      || fieldText.includes("files touched");
    if (hasStrongOutcome) {
      return 82;
    }
    return isGenericStatusText(details.lead) ? 20 : 55;
  }
  if (event.event_type === "tool_use") {
    const hasActionSignal =
      combinedText.includes("publish")
      || combinedText.includes("commit")
      || combinedText.includes("verify")
      || combinedText.includes("dispatch")
      || fieldText.includes("task")
      || fieldText.includes("file");
    return hasActionSignal ? 58 : 25;
  }
  if (event.event_type === "assistant_message" || event.event_type === "user_message") {
    if (isPromptLikeText(event.content)) {
      return 0;
    }
    return isGenericStatusText(details.lead) ? 20 : 72;
  }
  return isGenericStatusText(details.lead) ? 18 : 48;
}

function buildSessionDetailBlocks(events: TimelineEvent[]): SessionDetailBlock[] {
  const blocks: SessionDetailBlock[] = [];

  for (let index = 0; index < events.length; index += 1) {
    const event = events[index];
    const nextEvent = events[index + 1];

    if (
      event.event_type === "tool_use"
      && nextEvent
      && nextEvent.event_type === "tool_result"
      && nextEvent.turn === event.turn
      && nextEvent.tool_name === event.tool_name
    ) {
      const useDetails = buildEventDetails(event);
      const resultDetails = buildEventDetails(nextEvent);
      const mergedText = dedupeTextBlocks([
        resultDetails.lead,
        useDetails.lead,
        ...resultDetails.textBlocks,
        ...useDetails.textBlocks,
      ].filter((value): value is string => Boolean(value)));
      const mergedFields = dedupeDetailFields([...useDetails.fields, ...resultDetails.fields]);
      const mergedLead = mergedText[0] ?? resultDetails.lead ?? useDetails.lead ?? null;
      const resultScore = eventImportanceScore(nextEvent, resultDetails);

      blocks.push({
        id: `${event.id}:${nextEvent.id}`,
        timestamp: nextEvent.created_at,
        eventType: nextEvent.event_type,
        label: event.tool_name || "Tool",
        title: event.tool_name ? `${event.tool_name}` : "Tool activity",
        lead: mergedLead,
        textBlocks: mergedLead ? mergedText.slice(1) : mergedText,
        fields: mergedFields,
        score: Math.max(resultScore, 48),
        defaultVisible: resultScore >= 60,
      });
      index += 1;
      continue;
    }

    const details = buildEventDetails(event);
    const score = eventImportanceScore(event, details);
    blocks.push({
      id: event.id,
      timestamp: event.created_at,
      eventType: event.event_type,
      label: event.tool_name || eventSummaryLabel(event.event_type),
      title: event.tool_name || eventSummaryLabel(event.event_type),
      lead: details.lead,
      textBlocks: details.lead ? details.textBlocks.slice(1) : details.textBlocks,
      fields: details.fields,
      score,
      defaultVisible: score >= 60,
    });
  }

  return blocks;
}

function blockMatchesIssueMarker(block: SessionDetailBlock, marker: PersonaIssueMarker): boolean {
  if (block.id === marker.event_id || block.id.split(":").includes(marker.event_id)) {
    return true;
  }
  const haystack = `${block.title ?? ""} ${block.lead ?? ""} ${block.textBlocks.join(" ")}`.toLowerCase();
  if (marker.tool_name && haystack.includes(marker.tool_name.toLowerCase())) {
    return true;
  }
  const markerWords = `${marker.title} ${marker.summary} ${marker.detail ?? ""}`
    .toLowerCase()
    .split(/\s+/)
    .filter((token) => token.length > 4);
  return markerWords.some((token) => haystack.includes(token));
}

function buildIssueDetailBlocks(
  blocks: SessionDetailBlock[],
  markers: PersonaIssueMarker[],
): SessionDetailBlock[] {
  const selected: SessionDetailBlock[] = [];
  const seen = new Set<string>();
  for (const marker of markers) {
    const match = blocks.find((block) => blockMatchesIssueMarker(block, marker));
    if (match && !seen.has(match.id)) {
      seen.add(match.id);
      selected.push(match);
    }
  }
  return selected;
}

function outcomeToneClasses(hasErrors: boolean): string {
  return hasErrors
    ? "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300"
    : "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300";
}

function rootCauseClasses(rootCause: string): string {
  switch (rootCause) {
    case "workflow":
      return "bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-950/40 dark:text-fuchsia-300";
    case "tool":
      return "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300";
    case "context":
      return "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300";
    case "infra":
      return "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300";
    case "prompt":
      return "bg-violet-100 text-violet-700 dark:bg-violet-950/40 dark:text-violet-300";
    default:
      return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";
  }
}

function formatRuntimeLabel(seconds: number | null): string | null {
  if (seconds == null) {
    return null;
  }
  if (seconds < 60) {
    return `${seconds}s median`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m median`;
  }
  return `${(seconds / 3600).toFixed(1)}h median`;
}

function EntryIssueSummary({
  issueMarkers,
}: {
  issueMarkers: PersonaIssueMarker[];
}) {
  const primaryMarker = issueMarkers[0];
  if (!primaryMarker) {
    return null;
  }
  const additionalCount = Math.max(issueMarkers.length - 1, 0);

  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/90 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/50">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", pulseTagClasses(primaryMarker.primary_tag))}>
          {pulseTagLabel(primaryMarker.primary_tag)}
        </span>
        {primaryMarker.primary_root_cause && (
          <span className={cn("rounded-full px-2 py-0.5 text-[11px]", rootCauseClasses(primaryMarker.primary_root_cause))}>
            {rootCauseLabel(primaryMarker.primary_root_cause)}
          </span>
        )}
        {additionalCount > 0 && (
          <span className="rounded-full bg-slate-200/80 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            +{additionalCount} more
          </span>
        )}
      </div>
      <div className="mt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">{primaryMarker.title}</div>
      <ExpandableText
        text={primaryMarker.summary}
        expandedText={primaryMarker.detail}
        className="mt-1 block whitespace-pre-wrap break-words text-sm text-slate-600 dark:text-slate-300"
        collapsedLength={160}
      />
    </div>
  );
}

function PulseOverviewPanels({
  visiblePulseMetrics,
  pulse,
  applyPulseFilter,
  inspectAgentPulse,
}: {
  visiblePulseMetrics: PersonaPulseSummary["metrics"];
  pulse: PersonaPulseSummary;
  applyPulseFilter: (nextMode: FilterMode, nextAnchorEntryId?: string | null) => void;
  inspectAgentPulse: (agentSlugValue: string) => void;
}) {
  if (visiblePulseMetrics.length === 0 && pulse.issue_groups.length === 0 && pulse.agent_scorecards.length === 0) {
    return null;
  }

  return (
    <div className="mb-5 space-y-4">
      {visiblePulseMetrics.length > 0 && (
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {visiblePulseMetrics.map((metric) => {
            const mode = pulseTagToFilterMode(metric.key);
            return (
              <button
                key={metric.key}
                type="button"
                onClick={() => applyPulseFilter(mode)}
                className={cn(
                  "rounded-2xl border px-3 py-3 text-left transition",
                  metric.count > 0
                    ? "border-slate-200 bg-slate-50 hover:border-slate-300 hover:bg-white dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-700 dark:hover:bg-slate-950"
                    : "border-slate-200/70 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-900/60",
                )}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", pulseTagClasses(metric.key))}>
                    {metric.label}
                  </span>
                  <span className="text-lg font-semibold text-slate-900 dark:text-slate-100">{metric.count}</span>
                </div>
                <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{metric.description}</p>
              </button>
            );
          })}
        </div>
      )}

      {(pulse.issue_groups.length > 0 || pulse.agent_scorecards.length > 0) && (
        <div className="grid gap-4 xl:grid-cols-[1.3fr_1fr]">
          <section className="rounded-2xl border border-slate-200 bg-slate-50/90 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/70">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">
              <AlertCircle className="h-3.5 w-3.5" />
              Repeated Friction
            </div>
            {pulse.issue_groups.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">No repeated issue fingerprints in this window.</p>
            ) : (
              <div className="mt-3 space-y-3">
                {pulse.issue_groups.map((issue) => (
                  <button
                    key={issue.fingerprint}
                    type="button"
                    onClick={() => applyPulseFilter(pulseTagToFilterMode(issue.primary_tag), issue.latest_entry_id)}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-left transition hover:border-slate-300 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-slate-700"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", pulseTagClasses(issue.primary_tag))}>
                        {pulseTagLabel(issue.primary_tag)}
                      </span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                        {issue.count} hits
                      </span>
                      {issue.root_cause && (
                        <span className={cn("rounded-full px-2 py-0.5 text-[11px]", rootCauseClasses(issue.root_cause))}>
                          {rootCauseLabel(issue.root_cause)}
                        </span>
                      )}
                    </div>
                    <div className="mt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">{issue.title}</div>
                    <ExpandableText
                      text={issue.summary}
                      className="mt-1 block whitespace-pre-wrap break-words text-sm text-slate-600 dark:text-slate-300"
                      collapsedLength={160}
                    />
                    <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400 dark:text-slate-500">
                      {issue.agent_slugs.map((agentSlugValue) => (
                        <span key={`${issue.fingerprint}-${agentSlugValue}`} className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">
                          {agentSlugValue}
                        </span>
                      ))}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>
          <section className="rounded-2xl border border-slate-200 bg-slate-50/90 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/70">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">
              <Sparkles className="h-3.5 w-3.5" />
              Agent Scorecards
            </div>
            {pulse.agent_scorecards.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">No agent sessions in this window yet.</p>
            ) : (
              <div className="mt-3 space-y-3">
                {pulse.agent_scorecards.map((scorecard) => {
                  const successRate = scorecard.session_count > 0
                    ? Math.round((scorecard.success_count / scorecard.session_count) * 100)
                    : 0;
                  const runtimeLabel = formatRuntimeLabel(scorecard.median_runtime_seconds);
                  return (
                    <button
                      key={scorecard.agent_slug}
                      type="button"
                      onClick={() => inspectAgentPulse(scorecard.agent_slug)}
                      className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-left transition hover:border-slate-300 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-slate-700"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">{scorecard.label}</div>
                          <div className="text-xs text-slate-500 dark:text-slate-400">{successRate}% completed across {scorecard.session_count} runs</div>
                        </div>
                        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", scorecard.friction_count > 0 ? pulseTagClasses("friction") : pulseTagClasses("recovered"))}>
                          {scorecard.friction_count > 0 ? `${scorecard.friction_count} friction` : "steady"}
                        </span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500 dark:text-slate-400">
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{scorecard.error_count} errors</span>
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{scorecard.tool_friction_count} tool friction</span>
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{scorecard.instruction_drift_count} drift</span>
                        {runtimeLabel && <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{runtimeLabel}</span>}
                      </div>
                      {(scorecard.top_issue || scorecard.top_root_cause) && (
                        <div className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                          {scorecard.top_issue ?? "Primary friction trend"}
                          {scorecard.top_root_cause ? ` · ${rootCauseLabel(scorecard.top_root_cause)}` : ""}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function SessionDetailBlockCard({
  block,
}: {
  block: SessionDetailBlock;
}) {
  const headerTime = formatTimeLabel(new Date(block.timestamp));

  return (
    <div className={cn("rounded-xl border px-3 py-3 text-sm", eventToneClasses(block.eventType))}>
      <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.14em]">
        <span className={cn("rounded-full px-2 py-0.5", eventAccentClasses(block.eventType))}>
          {eventSummaryLabel(block.eventType)}
        </span>
        <time dateTime={block.timestamp} className="inline-flex items-center gap-1 normal-case tracking-normal opacity-80">
          <Clock3 className="h-3 w-3" />
          {headerTime}
        </time>
        {block.title && <span className="normal-case tracking-normal font-medium">{block.title}</span>}
      </div>
      {block.lead && (
        <div className="mt-2 rounded-xl border border-black/5 bg-white/70 px-2.5 py-2 dark:border-white/5 dark:bg-slate-950/60">
          <ExpandableText
            text={block.lead}
            className="block whitespace-pre-wrap break-words text-sm font-medium"
            collapsedLength={240}
          />
        </div>
      )}
      {block.textBlocks.map((text, index) => (
        <ExpandableText
          key={`${block.id}-text-${index}`}
          text={text}
          className="mt-2 block whitespace-pre-wrap break-words text-sm"
          collapsedLength={240}
        />
      ))}
      {block.fields.length > 0 && (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {block.fields.map((field) => (
            <div
              key={`${block.id}-${field.label}-${field.value}`}
              className="rounded-xl border border-black/5 bg-white/70 px-3 py-2 dark:border-white/5 dark:bg-slate-950/60"
            >
              <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">
                {field.label}
              </div>
              <div
                className={cn(
                  "mt-1 rounded-lg px-2 py-1",
                  field.tone ? badgeToneClasses(field.tone) : "bg-slate-100/80 dark:bg-slate-900/70",
                )}
              >
                <ExpandableText
                  text={field.value}
                  className="block whitespace-pre-wrap break-words text-sm"
                  collapsedLength={220}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function entryStatusClasses(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === "failed" || normalized === "error") {
    return "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300";
  }
  if (normalized === "completed") {
    return "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300";
  }
  if (normalized === "active") {
    return "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300";
  }
  if (normalized === "paused") {
    return "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300";
  }
  return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";
}

function heartbeatIsImportant(entry: PersonaStreamEntry): boolean {
  const summary = `${entry.summary_oneliner ?? ""} ${entry.live_summary ?? ""}`.toLowerCase();
  const importantKeywords = [
    "dispatch",
    "publish",
    "verified",
    "verify",
    "fixed",
    "created ",
    "reconciled",
    "merged",
    "review",
    "audit",
    "error",
    "failed",
    "blocked",
    "warning",
    "assess",
    "investig",
    "task-",
  ];
  return importantKeywords.some((keyword) => summary.includes(keyword));
}

function isRoutineHeartbeatBlock(
  block: ItemTimelineBlock,
  searchActive: boolean,
  filterMode: FilterMode,
): boolean {
  if (searchActive || filterMode !== "all") {
    return false;
  }
  if (block.anchorItem.kind !== "heartbeat") {
    return false;
  }
  if (block.childRuns.length > 0) {
    return false;
  }
  const entry = block.anchorItem.entry;
  if (entry.status !== "completed" || entry.live_status === "active") {
    return false;
  }
  if (entry.event_previews.some((preview) => preview.event_type === "error")) {
    return false;
  }
  if (entry.event_previews.length > 4) {
    return false;
  }
  if (heartbeatIsImportant(entry)) {
    return false;
  }
  const summary = `${entry.summary_oneliner ?? ""} ${entry.live_summary ?? ""}`.toLowerCase();
  if (summary.trim().length > 140) {
    return false;
  }
  return (
    (entry.tool_count <= 2 && entry.message_count <= 0)
    || summary.includes("waiting for model")
    || summary.includes("execution completed")
  );
}

function mergeEventPreviews(
  original: PersonaStreamEventPreview[],
  live: PersonaStreamEventPreview[],
): PersonaStreamEventPreview[] {
  if (live.length === 0) {
    return original;
  }
  const deduped = new Map<string, PersonaStreamEventPreview>();
  for (const preview of [...live, ...original]) {
    if (!deduped.has(preview.id)) {
      deduped.set(preview.id, preview);
    }
  }
  return Array.from(deduped.values()).slice(0, 12);
}

function buildLivePreview(event: LiveSessionEvent): PersonaStreamEventPreview | null {
  const previewId = `live:${event.session_id}:${event.timestamp}:${event.event_type}`;
  if (event.event_type === "message") {
    const role =
      typeof event.data === "object" && event.data && "role" in event.data && typeof event.data.role === "string"
        ? event.data.role
        : null;
    const content =
      typeof event.data === "object" && event.data && "content" in event.data && typeof event.data.content === "string"
        ? event.data.content
        : null;
    return {
      id: previewId,
      event_type: role ? `${role}_message` : "assistant_message",
      created_at: event.timestamp,
      role,
      tool_name: null,
      content_preview: content,
      tool_input_preview: null,
      tool_output_preview: null,
      duration_ms: null,
      model_used: null,
    };
  }
  if (event.event_type === "tool_use") {
    const toolName =
      typeof event.data === "object" && event.data && "tool_name" in event.data && typeof event.data.tool_name === "string"
        ? event.data.tool_name
        : null;
    const toolInput =
      typeof event.data === "object" && event.data && "tool_input" in event.data
        ? JSON.stringify(event.data.tool_input)
        : null;
    const toolOutput =
      typeof event.data === "object" && event.data && "tool_output" in event.data
        ? JSON.stringify(event.data.tool_output)
        : null;
    return {
      id: previewId,
      event_type: "tool_use",
      created_at: event.timestamp,
      role: null,
      tool_name: toolName,
      content_preview: null,
      tool_input_preview: toolInput,
      tool_output_preview: toolOutput,
      duration_ms: null,
      model_used: null,
    };
  }
  if (event.event_type === "tool_result") {
    const toolName =
      typeof event.data === "object" && event.data && "tool_name" in event.data && typeof event.data.tool_name === "string"
        ? event.data.tool_name
        : null;
    const toolOutput =
      typeof event.data === "object" && event.data && "tool_output" in event.data
        ? JSON.stringify(event.data.tool_output)
        : null;
    const durationMs =
      typeof event.data === "object" && event.data && "duration_ms" in event.data && typeof event.data.duration_ms === "number"
        ? event.data.duration_ms
        : null;
    const outputObject =
      typeof event.data === "object" && event.data && "tool_output" in event.data && typeof event.data.tool_output === "object"
        ? event.data.tool_output
        : null;
    const contentPreview =
      outputObject && "content" in outputObject && typeof outputObject.content === "string"
        ? outputObject.content
        : null;
    return {
      id: previewId,
      event_type: "tool_result",
      created_at: event.timestamp,
      role: null,
      tool_name: toolName,
      content_preview: contentPreview,
      tool_input_preview: null,
      tool_output_preview: toolOutput,
      duration_ms: durationMs,
      model_used: null,
    };
  }
  if (event.event_type === "error") {
    const errorMessage =
      typeof event.data === "object" && event.data && "error_message" in event.data && typeof event.data.error_message === "string"
        ? event.data.error_message
        : "Session error";
    return {
      id: previewId,
      event_type: "error",
      created_at: event.timestamp,
      role: null,
      tool_name: null,
      content_preview: errorMessage,
      tool_input_preview: null,
      tool_output_preview: null,
      duration_ms: null,
      model_used: null,
    };
  }
  if (event.event_type === "complete") {
    return {
      id: previewId,
      event_type: "tool_result",
      created_at: event.timestamp,
      role: null,
      tool_name: null,
      content_preview: "Execution completed",
      tool_input_preview: null,
      tool_output_preview: null,
      duration_ms: null,
      model_used: null,
    };
  }
  return null;
}

function liveSummaryFromEvent(event: LiveSessionEvent): string | null {
  if (event.event_type === "tool_use") {
    const toolName =
      typeof event.data === "object" && event.data && "tool_name" in event.data && typeof event.data.tool_name === "string"
        ? event.data.tool_name
        : "tool";
    return `Running ${toolName}`;
  }
  if (event.event_type === "tool_result") {
    const toolName =
      typeof event.data === "object" && event.data && "tool_name" in event.data && typeof event.data.tool_name === "string"
        ? event.data.tool_name
        : "tool";
    const toolOutput =
      typeof event.data === "object" && event.data && "tool_output" in event.data && typeof event.data.tool_output === "object"
        ? event.data.tool_output
        : null;
    const content =
      toolOutput && "content" in toolOutput && typeof toolOutput.content === "string"
        ? toolOutput.content
        : null;
    const isError =
      typeof event.data === "object" && event.data && "is_error" in event.data && typeof event.data.is_error === "boolean"
        ? event.data.is_error
        : toolOutput && "is_error" in toolOutput && typeof toolOutput.is_error === "boolean"
          ? toolOutput.is_error
          : false;
    if (isError) {
      return `Tool failed: ${toolName}`;
    }
    return content ? shortenText(content, 96) : `Waiting for model after ${toolName}`;
  }
  if (event.event_type === "message") {
    const content =
      typeof event.data === "object" && event.data && "content" in event.data && typeof event.data.content === "string"
        ? event.data.content
        : null;
    return content ? shortenText(content, 96) : "New message";
  }
  if (event.event_type === "error") {
    const errorMessage =
      typeof event.data === "object" && event.data && "error_message" in event.data && typeof event.data.error_message === "string"
        ? event.data.error_message
        : "Session error";
    return `Error: ${shortenText(errorMessage, 88)}`;
  }
  if (event.event_type === "complete") {
    return "Execution completed";
  }
  if (event.event_type === "session_start") {
    return "Session started";
  }
  return null;
}

function liveStatusFromEvent(event: LiveSessionEvent): string | null {
  if (event.event_type === "complete") {
    return "completed";
  }
  if (event.event_type === "error") {
    return "failed";
  }
  if (event.event_type === "tool_result") {
    const toolOutput =
      typeof event.data === "object" && event.data && "tool_output" in event.data && typeof event.data.tool_output === "object"
        ? event.data.tool_output
        : null;
    const isError =
      typeof event.data === "object" && event.data && "is_error" in event.data && typeof event.data.is_error === "boolean"
        ? event.data.is_error
        : toolOutput && "is_error" in toolOutput && typeof toolOutput.is_error === "boolean"
          ? toolOutput.is_error
          : false;
    return isError ? "failed" : "active";
  }
  return "active";
}

function SessionDetailsPanel({
  details,
  previewCount,
  issueMarkers,
  activeIssueTag,
}: {
  details: SessionEventDetailsState | undefined;
  previewCount: number;
  issueMarkers: PersonaIssueMarker[];
  activeIssueTag: string | null;
}) {
  const [showFullTrace, setShowFullTrace] = useState(false);
  const detailEvents = details?.events ?? [];
  const detailResetKey = useMemo(
    () => detailEvents.map((event) => event.id).join("|"),
    [detailEvents],
  );
  const blocks = useMemo(() => buildSessionDetailBlocks(detailEvents), [detailEvents]);
  const filteredIssueMarkers = useMemo(() => filterIssueMarkers(issueMarkers, activeIssueTag), [activeIssueTag, issueMarkers]);
  const issueBlocks = useMemo(
    () => buildIssueDetailBlocks(blocks, filteredIssueMarkers),
    [blocks, filteredIssueMarkers],
  );
  const importantBlocks = useMemo(
    () => blocks.filter((block) => block.defaultVisible && !issueBlocks.some((issueBlock) => issueBlock.id === block.id)),
    [blocks, issueBlocks],
  );
  const visibleImportantBlocks = useMemo(
    () => {
      if (importantBlocks.length > 0) {
        return importantBlocks.slice(0, 6);
      }
      const fallbackBlocks = blocks.filter((block) => block.score > 0).slice(0, Math.min(blocks.length, 3));
      return fallbackBlocks.length > 0 ? fallbackBlocks : blocks.slice(0, 1);
    },
    [blocks, importantBlocks],
  );

  useEffect(() => {
    setShowFullTrace(false);
  }, [detailResetKey]);

  if (!details || details.loading) {
    return (
      <div className="mt-3 flex items-center gap-2 border-t border-slate-200 pt-3 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading full session detail…
      </div>
    );
  }

  if (details.error) {
    return (
      <div className="mt-3 rounded-2xl border border-rose-200 bg-rose-50 px-3 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300">
        {details.error}
      </div>
    );
  }

  if (details.events.length === 0) {
    return (
      <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-950/50 dark:text-slate-400">
        No additional detail was recorded for this session.
      </div>
    );
  }
  const totalHiddenCount = Math.max(blocks.length - visibleImportantBlocks.length, 0);
  const errorCount = blocks.filter((block) => block.eventType === "error").length;
  const toolActivityCount = blocks.filter(
    (block) => block.eventType === "tool_use" || block.eventType === "tool_result",
  ).length;
  const issueCount = filteredIssueMarkers.length;
  const visibleSectionTitle = showFullTrace ? "Full trace" : "Important events";
  const visibleSectionDescription = showFullTrace
    ? "Every recorded step is shown below in chronological order."
    : "Only the highest-signal steps are shown first. Routine chatter stays hidden until you ask for it.";
  const visibleBlocks = showFullTrace ? blocks : visibleImportantBlocks;
  const totalSummaryMarkers = previewCount > 0 ? `${previewCount} summary marker${previewCount === 1 ? "" : "s"}` : null;
  const overviewBadges = [
    `${blocks.length} event${blocks.length === 1 ? "" : "s"} recorded`,
    `${visibleImportantBlocks.length} key event${visibleImportantBlocks.length === 1 ? "" : "s"} surfaced`,
    issueCount > 0 ? `${issueCount} issue${issueCount === 1 ? "" : "s"} highlighted` : "No issue markers",
    totalHiddenCount > 0 ? `${totalHiddenCount} routine item${totalHiddenCount === 1 ? "" : "s"} hidden` : "No routine items hidden",
    toolActivityCount > 0 ? `${toolActivityCount} tool step${toolActivityCount === 1 ? "" : "s"}` : null,
    errorCount > 0 ? `${errorCount} error${errorCount === 1 ? "" : "s"}` : "No errors recorded",
    totalSummaryMarkers,
  ].filter((value): value is string => Boolean(value));

  return (
    <div className="mt-3 space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
      <section className="space-y-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">
          Overview
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50/90 px-3 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/60 dark:text-slate-300">
          <div className="flex flex-wrap gap-2">
            {overviewBadges.map((badge) => (
              <span
                key={badge}
                className={cn(
                  "rounded-full px-2.5 py-1 text-xs font-medium",
                  badge.toLowerCase().includes("error") && !badge.toLowerCase().includes("no errors")
                    ? outcomeToneClasses(true)
                    : "bg-slate-200/80 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
                )}
              >
                {badge}
              </span>
            ))}
          </div>
        </div>
      </section>

      {filteredIssueMarkers.length > 0 && (
        <section className="space-y-2">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">
              Issues
            </div>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              The events below are the most likely sources of friction or failure in this run.
            </p>
          </div>
          <div className="space-y-2">
            {issueBlocks.length > 0 ? (
              issueBlocks.slice(0, 4).map((block) => <SessionDetailBlockCard key={`issue-${block.id}`} block={block} />)
            ) : (
              filteredIssueMarkers.slice(0, 4).map((marker) => (
                <div
                  key={`issue-marker-${marker.event_id}-${marker.primary_tag}`}
                  className="rounded-xl border border-slate-200 bg-slate-50/90 px-3 py-3 dark:border-slate-800 dark:bg-slate-950/50"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", pulseTagClasses(marker.primary_tag))}>
                      {pulseTagLabel(marker.primary_tag)}
                    </span>
                    {marker.primary_root_cause && (
                      <span className={cn("rounded-full px-2 py-0.5 text-[11px]", rootCauseClasses(marker.primary_root_cause))}>
                        {rootCauseLabel(marker.primary_root_cause)}
                      </span>
                    )}
                  </div>
                  <div className="mt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">{marker.title}</div>
                  <ExpandableText
                    text={marker.summary}
                    expandedText={marker.detail}
                    className="mt-1 block whitespace-pre-wrap break-words text-sm text-slate-600 dark:text-slate-300"
                    collapsedLength={220}
                  />
                </div>
              ))
            )}
          </div>
        </section>
      )}

      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">
              {visibleSectionTitle}
            </div>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {visibleSectionDescription}
            </p>
          </div>
          {blocks.length > visibleImportantBlocks.length && (
            <button
              type="button"
              onClick={() => setShowFullTrace((current) => !current)}
              className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
            >
              {showFullTrace ? (
                <>
                  <ChevronUp className="h-3.5 w-3.5" />
                  Show key events
                </>
              ) : (
                <>
                  <ChevronDown className="h-3.5 w-3.5" />
                  Show full trace ({blocks.length} events)
                </>
              )}
            </button>
          )}
        </div>
        <div className="space-y-2">
          {visibleBlocks.map((block) => (
            <SessionDetailBlockCard key={block.id} block={block} />
          ))}
        </div>
      </section>
    </div>
  );
}

function RoutineHeartbeatGroup({
  block,
  expanded,
  onToggle,
  activeSessionId,
  activeIssueTag,
  expandedEntryIds,
  onToggleEntry,
  sessionEventDetails,
}: {
  block: RoutineHeartbeatTimelineBlock;
  expanded: boolean;
  onToggle: () => void;
  activeSessionId: string | null;
  activeIssueTag: string | null;
  expandedEntryIds: Record<string, boolean>;
  onToggleEntry: (entryId: string, sessionId: string) => void;
  sessionEventDetails: Record<string, SessionEventDetailsState>;
}) {
  const first = block.items[0]?.anchorItem;
  const last = block.items.at(-1)?.anchorItem;
  const timeRange =
    first && last
      ? `${formatTimeLabel(first.timestamp)} to ${formatTimeLabel(last.timestamp)}`
      : null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/90 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/80">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
              <Clock3 className="h-4 w-4 text-slate-400" />
              {block.items.length} routine heartbeats
            </span>
            {timeRange && (
              <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {timeRange}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Routine checks stay collapsed until you need the full detail.
          </p>
        </div>
        <button
          type="button"
          onClick={onToggle}
          className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {expanded ? "Hide routine checks" : "Show routine checks"}
        </button>
      </div>
      {expanded && (
        <div className="mt-3 space-y-3 border-t border-slate-200 pt-3 dark:border-slate-800">
          {block.items.map(({ anchorItem }) => (
            <div
              key={anchorItem.id}
              data-session-anchor={anchorItem.sessionId}
              data-testid="stream-item"
              data-stream-item-id={anchorItem.id}
              data-timestamp={anchorItem.timestamp.toISOString()}
              className="flex items-start gap-3"
            >
              <TimelineTimestamp timestamp={anchorItem.timestamp} />
              <div className="min-w-0 flex-1">
                <HeartbeatCard
                  entry={anchorItem.entry}
                  activeIssueTag={activeIssueTag}
                  selected={anchorItem.sessionId === activeSessionId}
                  expanded={!!expandedEntryIds[anchorItem.id]}
                  onToggle={() => onToggleEntry(anchorItem.id, anchorItem.sessionId)}
                  details={sessionEventDetails[anchorItem.sessionId]}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ChildRunStack({
  childRuns,
  activeSessionId,
  activeIssueTag,
  expandedEntryIds,
  onToggle,
  matchedIds,
  activeMatchId,
  sessionEventDetails,
}: {
  childRuns: FeedChildRun[];
  activeSessionId: string | null;
  activeIssueTag: string | null;
  expandedEntryIds: Record<string, boolean>;
  onToggle: (entryId: string, sessionId: string) => void;
  matchedIds: Set<string>;
  activeMatchId: string | null;
  sessionEventDetails: Record<string, SessionEventDetailsState>;
}) {
  return (
    <div className="ml-5 mt-3 border-l border-dashed border-sky-200 pl-4 dark:border-sky-900">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-600 dark:text-sky-300">
        Spawned Agents
      </div>
      <div className="space-y-3">
        {childRuns.map((childRun) => {
          const selected = childRun.sessionId === activeSessionId;
          const matched = matchedIds.has(childRun.id);
          const activeMatched = activeMatchId === childRun.id;

          return (
            <div
              key={childRun.id}
              data-session-anchor={childRun.sessionId}
              data-testid="stream-item"
              data-stream-item-id={childRun.id}
              data-timestamp={childRun.timestamp.toISOString()}
              className={cn(
                "flex items-start gap-3 rounded-2xl",
                matched && "px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
                activeMatched && "ring-2 ring-amber-400 dark:ring-amber-500",
              )}
            >
              <TimelineTimestamp timestamp={childRun.timestamp} />
              <div className="min-w-0 flex-1">
                <ChildRunCard
                  entry={childRun.entry}
                  activeIssueTag={activeIssueTag}
                  selected={selected}
                  expanded={!!expandedEntryIds[childRun.id]}
                  onToggle={() => onToggle(childRun.id, childRun.sessionId)}
                  details={sessionEventDetails[childRun.sessionId]}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ChildRunCard({
  entry,
  activeIssueTag,
  selected,
  expanded,
  onToggle,
  details,
}: {
  entry: PersonaStreamEntry;
  activeIssueTag: string | null;
  selected: boolean;
  expanded: boolean;
  onToggle: () => void;
  details?: SessionEventDetailsState;
}) {
  const issueMarkers = visibleIssueMarkers(entry, activeIssueTag);
  const showPulseSummary = shouldRenderPulseSummary(entry.pulse_summary, issueMarkers);
  const primaryIssue = issueMarkers[0];
  const visiblePulseTags = entry.pulse_tags.filter(
    (tag) => tag !== "friction" && tag !== primaryIssue?.primary_tag,
  );
  const visibleRootCauses = entry.root_causes.filter((rootCause) => rootCause !== primaryIssue?.primary_root_cause);

  return (
    <div
      className={cn(
        "rounded-2xl border px-4 py-3",
        selected
          ? "border-sky-300 bg-sky-50/70 dark:border-sky-700 dark:bg-sky-950/30"
          : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-full bg-sky-100 p-2 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300">
          <Bot className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {entry.agent_slug || "Agent"} on {entry.project_id}
            </span>
            <span className={cn("rounded-full px-2 py-0.5 text-[11px]", entryStatusClasses(entry.status))}>
              {entry.status}
            </span>
            {entry.tool_count > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                <Wrench className="h-3 w-3" />
                {entry.tool_count}
              </span>
            )}
          </div>
          <ExpandableText
            text={entry.summary_oneliner || entry.live_summary || "Child run activity"}
            className="mt-1 block text-sm text-slate-600 dark:text-slate-300"
            collapsedLength={220}
          />
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400 dark:text-slate-500">
            {entry.external_id && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">task {entry.external_id}</span>}
            {entry.current_branch && <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{entry.current_branch}</span>}
            {visiblePulseTags.map((tag) => (
              <span key={`${entry.session_id}-${tag}`} className={cn("rounded-full px-2 py-0.5", pulseTagClasses(tag))}>
                {pulseTagLabel(tag)}
              </span>
            ))}
            {visibleRootCauses.map((rootCause) => (
              <span
                key={`${entry.session_id}-${rootCause}`}
                className={cn("rounded-full px-2 py-0.5", rootCauseClasses(rootCause))}
              >
                {rootCauseLabel(rootCause)}
              </span>
            ))}
          </div>
          {showPulseSummary && entry.pulse_summary && (
            <ExpandableText
              text={entry.pulse_summary}
              className="mt-2 block text-xs text-slate-500 dark:text-slate-400"
              collapsedLength={180}
            />
          )}
          <EntryIssueSummary issueMarkers={issueMarkers} />
          {(entry.event_previews.length > 0 || details) && (
            <button
              type="button"
              onClick={onToggle}
              className="mt-3 inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              {expanded ? "Hide run details" : "Show run details"}
            </button>
          )}
          {expanded && (
            <SessionDetailsPanel
              details={details}
              previewCount={entry.event_previews.length}
              issueMarkers={issueMarkers}
              activeIssueTag={activeIssueTag}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function HeartbeatCard({
  entry,
  activeIssueTag,
  selected,
  expanded,
  onToggle,
  details,
}: {
  entry: PersonaStreamEntry;
  activeIssueTag: string | null;
  selected: boolean;
  expanded: boolean;
  onToggle: () => void;
  details?: SessionEventDetailsState;
}) {
  const issueMarkers = visibleIssueMarkers(entry, activeIssueTag);
  const showPulseSummary = shouldRenderPulseSummary(entry.pulse_summary, issueMarkers);
  const primaryIssue = issueMarkers[0];
  const visiblePulseTags = entry.pulse_tags.filter(
    (tag) => tag !== "friction" && tag !== primaryIssue?.primary_tag,
  );
  const visibleRootCauses = entry.root_causes.filter((rootCause) => rootCause !== primaryIssue?.primary_root_cause);

  return (
    <div
      className={cn(
        "rounded-2xl border px-4 py-3",
        selected
          ? "border-amber-300 bg-amber-50/80 dark:border-amber-700 dark:bg-amber-950/30"
          : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-full bg-amber-100 p-2 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300">
          <HeartPulse className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Heartbeat
            </span>
            <span className={cn("rounded-full px-2 py-0.5 text-[11px]", entryStatusClasses(entry.status))}>
              {entry.status}
            </span>
            {entry.tool_count > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                <Wrench className="h-3 w-3" />
                {entry.tool_count}
              </span>
            )}
          </div>
          <ExpandableText
            text={entry.summary_oneliner || entry.live_summary || "Routine check completed"}
            className="mt-1 block text-sm text-slate-600 dark:text-slate-300"
            collapsedLength={220}
          />
          {entry.live_summary && entry.summary_oneliner !== entry.live_summary && !isGenericStatusText(entry.live_summary) && (
            <ExpandableText
              text={entry.live_summary}
              className="mt-2 block text-xs text-slate-400 dark:text-slate-500"
              collapsedLength={180}
            />
          )}
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400 dark:text-slate-500">
            {entry.external_id && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">{entry.external_id}</span>}
            {visiblePulseTags.map((tag) => (
              <span key={`${entry.session_id}-${tag}`} className={cn("rounded-full px-2 py-0.5", pulseTagClasses(tag))}>
                {pulseTagLabel(tag)}
              </span>
            ))}
            {visibleRootCauses.map((rootCause) => (
              <span
                key={`${entry.session_id}-${rootCause}`}
                className={cn("rounded-full px-2 py-0.5", rootCauseClasses(rootCause))}
              >
                {rootCauseLabel(rootCause)}
              </span>
            ))}
          </div>
          {showPulseSummary && entry.pulse_summary && (
            <ExpandableText
              text={entry.pulse_summary}
              className="mt-2 block text-xs text-slate-500 dark:text-slate-400"
              collapsedLength={180}
            />
          )}
          <EntryIssueSummary issueMarkers={issueMarkers} />
          {(entry.event_previews.length > 0 || details) && (
            <button
              type="button"
              onClick={onToggle}
              className="mt-3 inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              {expanded ? "Hide heartbeat details" : "Show heartbeat details"}
            </button>
          )}
          {expanded && (
            <SessionDetailsPanel
              details={details}
              previewCount={entry.event_previews.length}
              issueMarkers={issueMarkers}
              activeIssueTag={activeIssueTag}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export function UnifiedPersonaWorkspace({
  agentSlug,
  activeSessionId,
  sidebarRefreshTrigger,
  runtimeSyncKey,
  onSelectSession,
  onSessionCreated,
  onNewSession,
}: UnifiedPersonaWorkspaceProps) {
  const searchInputId = useId();
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [search, setSearch] = useState("");
  const [filterMode, setFilterMode] = useState<FilterMode>("all");
  const [autoFollow, setAutoFollow] = useState(true);
  const deferredSearch = useDeferredValue(search);
  const [entries, setEntries] = useState<PersonaStreamEntry[]>([]);
  const [pulse, setPulse] = useState<PersonaPulseSummary>(EMPTY_PULSE);
  const [searchMatches, setSearchMatches] = useState<PersonaStreamMatch[]>([]);
  const [matchCount, setMatchCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [focusSessionId, setFocusSessionId] = useState<string | null>(null);
  const [anchorEntryId, setAnchorEntryId] = useState<string | null>(null);
  const [expandedEntryIds, setExpandedEntryIds] = useState<Record<string, boolean>>({});
  const [expandedRoutineGroupIds, setExpandedRoutineGroupIds] = useState<Record<string, boolean>>({});
  const [activeSearchMatchId, setActiveSearchMatchId] = useState<string | null>(null);
  const [liveRefreshTick, setLiveRefreshTick] = useState(0);
  const [liveSessionPatches, setLiveSessionPatches] = useState<Record<string, LiveSessionPatch>>({});
  const [sessionEventDetails, setSessionEventDetails] = useState<Record<string, SessionEventDetailsState>>({});
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [firstUnreadItemId, setFirstUnreadItemId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoFollowRef = useRef(true);
  const initialViewportTimeoutRef = useRef<number | null>(null);
  const programmaticScrollUntilRef = useRef(0);
  const initialViewportSettledRef = useRef(false);
  const lastReadItemIdRef = useRef<string | null>(null);
  const olderHistoryAnchorRef = useRef<{ scrollHeight: number; scrollTop: number } | null>(null);
  const sessionEventDetailsRef = useRef<Record<string, SessionEventDetailsState>>({});

  const apiConfig = useMemo(
    () => ({
      fetchHeaders: INTERNAL_HEADERS,
      completeEndpoint: `${getSseBaseUrl()}/api/complete`,
      sessionsEndpoint: `${getApiBaseUrl()}/api/sessions`,
      preferencesEndpoint: "/api/preferences",
      fetchFn: fetchApi,
      projectId: PROJECT_ID,
      memoryGroupPrefix: "agent:",
    }),
    [],
  );

  const {
    messages,
    status,
    error: chatError,
    currentSessionId,
    sendMessage,
    cancelStream,
  } = useChatStream({
    agentSlug,
    sessionId: activeSessionId || undefined,
    toolsEnabled: true,
    apiConfig,
    loadInitialSession: false,
  } as any);

  useEffect(() => {
    autoFollowRef.current = autoFollow;
  }, [autoFollow]);

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    const container = scrollRef.current;
    if (!container || typeof container.scrollTo !== "function") {
      return;
    }
    programmaticScrollUntilRef.current = Date.now() + PROGRAMMATIC_SCROLL_GRACE_MS;
    container.scrollTo({ top: container.scrollHeight, behavior });
  };

  const clearInitialViewportTimeout = useCallback(() => {
    if (initialViewportTimeoutRef.current != null) {
      window.clearTimeout(initialViewportTimeoutRef.current);
      initialViewportTimeoutRef.current = null;
    }
  }, []);

  useEffect(() => {
    sessionEventDetailsRef.current = sessionEventDetails;
  }, [sessionEventDetails]);

  const loadSessionEventDetails = useCallback(async (sessionId: string, force = false) => {
    const existing = sessionEventDetailsRef.current[sessionId];
    if (!force) {
      if (existing?.loading) {
        return;
      }
      if (existing && existing.events.length > 0 && !existing.error) {
        return;
      }
    }

    setSessionEventDetails((current) => ({
      ...current,
      [sessionId]: {
        loading: true,
        error: null,
        events: current[sessionId]?.events ?? [],
      },
    }));

    try {
      const allEvents: TimelineEvent[] = [];
      let pageNumber = 1;
      let total = 0;
      do {
        const response = await fetchSessionEvents(sessionId, { page: pageNumber, page_size: 500 });
        total = response.total;
        allEvents.push(...response.events);
        pageNumber += 1;
      } while (allEvents.length < total);

      allEvents.sort((left, right) => {
        const turnDifference = left.turn - right.turn;
        if (turnDifference !== 0) {
          return turnDifference;
        }
        const sequenceDifference = left.sequence - right.sequence;
        if (sequenceDifference !== 0) {
          return sequenceDifference;
        }
        return +new Date(left.created_at) - +new Date(right.created_at);
      });

      setSessionEventDetails((current) => ({
        ...current,
        [sessionId]: {
          loading: false,
          error: null,
          events: allEvents,
        },
      }));
    } catch (err) {
      setSessionEventDetails((current) => ({
        ...current,
        [sessionId]: {
          loading: false,
          error: err instanceof Error ? err.message : "Failed to load full session detail",
          events: current[sessionId]?.events ?? [],
        },
      }));
    }
  }, []);

  const hydratedEntries = useMemo(
    () =>
      entries.map((entry) => {
        const patch = liveSessionPatches[entry.session_id];
        if (!patch) {
          return entry;
        }
        return {
          ...entry,
          live_summary: patch.liveSummary ?? entry.live_summary,
          live_status: patch.liveStatus ?? entry.live_status,
          status:
            patch.liveStatus === "failed"
              ? "failed"
              : patch.liveStatus === "completed" && entry.status === "active"
                ? "completed"
                : entry.status,
          event_previews: mergeEventPreviews(entry.event_previews, patch.eventPreviews),
        };
      }),
    [entries, liveSessionPatches],
  );

  const mergedItems = useMemo(() => {
    const remote = buildRemoteFeedItems([...hydratedEntries].reverse());
    const local = buildLocalFeedMessages(messages, currentSessionId || activeSessionId);
    return [...remote, ...local]
      .filter((item) => {
        if (filterMode === "all") return true;
        if (filterMode === "messages") return item.kind === "message";
        if (filterMode === "heartbeats") return item.kind === "heartbeat";
        if (filterMode === "work") {
          return item.kind === "child_run" || item.kind === "heartbeat";
        }
        const pulseTag = filterModeToPulseTag(filterMode);
        if (pulseTag) {
          if (item.kind === "message") {
            return pulseTag === "error" ? /error|failed|warning|blocked/i.test(item.message.content) : false;
          }
          return entryHasPulseTag(item.entry, pulseTag);
        }
        return true;
      })
      .sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
  }, [hydratedEntries, messages, currentSessionId, activeSessionId, filterMode]);

  const selectedSessionId = focusSessionId ?? activeSessionId;
  const latestItemId = mergedItems.at(-1)?.id ?? null;

  function markLatestAsRead(itemId: string | null = latestItemId) {
    if (!itemId) {
      return;
    }
    lastReadItemIdRef.current = itemId;
    setFirstUnreadItemId(null);
  }

  const activeStreamSessionIds = useMemo(() => {
    const activeIds = new Set<string>();
    for (const entry of hydratedEntries) {
      if (entry.status === "active" || entry.live_status === "active") {
        activeIds.add(entry.session_id);
      }
    }
    return Array.from(activeIds);
  }, [hydratedEntries]);

  const { status: liveEventsStatus } = useSessionEvents({
    sessionIds: activeStreamSessionIds,
    autoConnect: true,
    autoReconnect: true,
    onEvent: (event) => {
      const preview = buildLivePreview(event);
      const liveSummary = liveSummaryFromEvent(event);
      const liveStatus = liveStatusFromEvent(event);
      setLiveSessionPatches((current) => {
        const existing = current[event.session_id] ?? {
          liveSummary: null,
          liveStatus: null,
          eventPreviews: [],
        };
        return {
          ...current,
          [event.session_id]: {
            liveSummary: liveSummary ?? existing.liveSummary,
            liveStatus: liveStatus ?? existing.liveStatus,
            eventPreviews: preview ? mergeEventPreviews(existing.eventPreviews, [preview]) : existing.eventPreviews,
          },
        };
      });
      if (!entries.some((entry) => entry.session_id === event.session_id)) {
        setLiveRefreshTick((value) => value + 1);
        return;
      }
      if (event.event_type === "complete" || event.event_type === "error") {
        window.setTimeout(() => {
          setLiveRefreshTick((value) => value + 1);
        }, 600);
      }
    },
  });

  useEffect(() => {
    if (!runtimeSyncKey) {
      return;
    }
    const expandedActiveSessionIds = Array.from(
      new Set(
        mergedItems
          .filter((item): item is FeedHeartbeat | FeedChildRun => item.kind !== "message")
          .filter((item) => expandedEntryIds[item.id] && activeStreamSessionIds.includes(item.sessionId))
          .map((item) => item.sessionId),
      ),
    );
    expandedActiveSessionIds.forEach((sessionId) => {
      void loadSessionEventDetails(sessionId, true);
    });
  }, [runtimeSyncKey, mergedItems, expandedEntryIds, activeStreamSessionIds, loadSessionEventDetails]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) {
      return;
    }
    const handleScroll = () => {
      const nearBottom = isNearBottom(container);
      setIsAtBottom(nearBottom);
      if (Date.now() < programmaticScrollUntilRef.current) {
        return;
      }
      if (nearBottom) {
        if (!autoFollowRef.current) {
          setAutoFollow(true);
        }
        if (latestItemId) {
          lastReadItemIdRef.current = latestItemId;
          setFirstUnreadItemId(null);
        }
        return;
      }
      if (autoFollowRef.current && !nearBottom) {
        clearInitialViewportTimeout();
        setAutoFollow(false);
      }
    };
    container.addEventListener("scroll", handleScroll, { passive: true });
    return () => container.removeEventListener("scroll", handleScroll);
  }, [clearInitialViewportTimeout, latestItemId]);

  useEffect(() => {
    if (currentSessionId) {
      onSessionCreated(currentSessionId);
    }
  }, [currentSessionId, onSessionCreated]);

  useEffect(() => {
    if (!deferredSearch.trim()) {
      setAnchorEntryId(null);
    }
    setPage(1);
  }, [timeRange, deferredSearch, focusSessionId, currentSessionId]);

  useEffect(() => {
    initialViewportSettledRef.current = false;
    clearInitialViewportTimeout();
  }, [timeRange, deferredSearch, focusSessionId, anchorEntryId, activeSessionId, clearInitialViewportTimeout]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const effectiveRange = deferredSearch.trim() ? "all" : timeRange;
      fetchPersonaStream({
      timeRange: effectiveRange,
      search: deferredSearch.trim() || undefined,
      focusSessionId,
      anchorEntryId,
      page,
      pageSize: PAGE_SIZE,
    })
      .then((data) => {
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setEntries((prev) => {
            if (page === 1) {
              return data.entries;
            }
            const merged = [...prev];
            for (const entry of data.entries) {
              if (!merged.some((existing) => existing.id === entry.id)) {
                merged.push(entry);
              }
            }
            return merged;
          });
          setTotal(data.total);
          setSearchMatches(data.matches);
          setMatchCount(data.match_count);
          setPulse(data.pulse ?? EMPTY_PULSE);
          setError(null);
        });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load stream");
          setPulse(EMPTY_PULSE);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [timeRange, deferredSearch, focusSessionId, anchorEntryId, page, currentSessionId, sidebarRefreshTrigger, liveRefreshTick, runtimeSyncKey]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container || !autoFollow) {
      return;
    }
    scrollToBottom("smooth");
    setIsAtBottom(true);
    markLatestAsRead();
  }, [messages.length, status, autoFollow]);

  useEffect(() => {
    if (initialViewportSettledRef.current || loading || !autoFollow) {
      return;
    }
    if (deferredSearch.trim() || focusSessionId || anchorEntryId) {
      return;
    }
    if (hydratedEntries.length === 0 && messages.length === 0) {
      return;
    }
    initialViewportSettledRef.current = true;
    clearInitialViewportTimeout();
    initialViewportTimeoutRef.current = window.setTimeout(() => {
      scrollToBottom("auto");
      setIsAtBottom(true);
      markLatestAsRead();
      initialViewportTimeoutRef.current = null;
    }, 0);
    return () => clearInitialViewportTimeout();
  }, [anchorEntryId, autoFollow, clearInitialViewportTimeout, deferredSearch, focusSessionId, hydratedEntries.length, loading, messages.length]);

  useEffect(() => {
    if (!latestItemId) {
      return;
    }
    if (!lastReadItemIdRef.current) {
      lastReadItemIdRef.current = latestItemId;
      return;
    }
    if (latestItemId === lastReadItemIdRef.current) {
      return;
    }
    if (autoFollow && isAtBottom) {
      markLatestAsRead(latestItemId);
      return;
    }
    const previousIndex = mergedItems.findIndex((item) => item.id === lastReadItemIdRef.current);
    const nextUnreadId = mergedItems[Math.max(previousIndex + 1, 0)]?.id ?? latestItemId;
    setFirstUnreadItemId((current) => current ?? nextUnreadId);
  }, [latestItemId, mergedItems, autoFollow, isAtBottom]);

  useEffect(() => {
    if (!autoFollow) {
      return;
    }
    const hasLiveWork = hydratedEntries.some((entry) => entry.status === "active" || entry.live_status === "active");
    if (!hasLiveWork) {
      return;
    }
    const container = scrollRef.current;
    if (!container || !isNearBottom(container)) {
      return;
    }
    scrollToBottom("smooth");
    setIsAtBottom(true);
    markLatestAsRead();
  }, [autoFollow, hydratedEntries]);

  useEffect(() => {
    const container = scrollRef.current;
    const anchor = olderHistoryAnchorRef.current;
    if (!container || !anchor || loading) {
      return;
    }
    const heightDelta = container.scrollHeight - anchor.scrollHeight;
    container.scrollTop = anchor.scrollTop + Math.max(heightDelta, 0);
    olderHistoryAnchorRef.current = null;
  }, [entries, loading]);

  useEffect(() => {
    const hasLiveWork = hydratedEntries.some((entry) => entry.status === "active" || entry.live_status === "active");
    if (!hasLiveWork || liveEventsStatus === "connected") {
      return;
    }
    const interval = window.setInterval(() => {
      setLiveRefreshTick((value) => value + 1);
    }, LIVE_REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [hydratedEntries, liveEventsStatus]);

  const groupedItems = useMemo(() => {
    const groups: Array<{ label: string; blocks: TimelineBlock[] }> = [];
    let currentLabel = "";
    for (const item of mergedItems) {
      const label = formatDayLabel(item.timestamp);
      if (label !== currentLabel) {
        currentLabel = label;
        groups.push({ label, blocks: [] });
      }
      const currentBlocks = groups[groups.length - 1].blocks;
      if (isChildRunItem(item) && item.entry.parent_session_id) {
        const parentBlockIndex = currentBlocks.findLastIndex(
          (block) =>
            block.kind === "item" &&
            canAnchorChildRuns(block.anchorItem) &&
            block.anchorItem.sessionId === item.entry.parent_session_id,
        );
        if (parentBlockIndex >= 0) {
          const parentBlock = currentBlocks[parentBlockIndex];
          if (parentBlock.kind === "item") {
            parentBlock.childRuns.push(item);
          }
          continue;
        }
      }
      currentBlocks.push({ kind: "item", anchorItem: item, childRuns: [] });
    }
    return groups.map((group) => {
      const compressedBlocks: TimelineBlock[] = [];
      let pendingRoutine: ItemTimelineBlock[] = [];
      const flushRoutine = () => {
        if (pendingRoutine.length === 0) {
          return;
        }
        if (pendingRoutine.length === 1) {
          compressedBlocks.push(pendingRoutine[0]);
        } else {
          compressedBlocks.push({
            kind: "routine_group",
            id: `routine:${pendingRoutine[0].anchorItem.id}:${pendingRoutine.at(-1)?.anchorItem.id}`,
            items: pendingRoutine.map((block) => ({
              anchorItem: block.anchorItem as FeedHeartbeat,
              childRuns: block.childRuns,
            })),
          });
        }
        pendingRoutine = [];
      };

      for (const block of group.blocks) {
        if (block.kind !== "item") {
          flushRoutine();
          compressedBlocks.push(block);
          continue;
        }
        if (isRoutineHeartbeatBlock(block, !!deferredSearch.trim(), filterMode)) {
          pendingRoutine.push(block);
          continue;
        }
        flushRoutine();
        compressedBlocks.push(block);
      }
      flushRoutine();
      return { ...group, blocks: compressedBlocks };
    });
  }, [mergedItems, deferredSearch, filterMode]);

  const timelineRows = useMemo(() => {
    const rows: TimelineRow[] = [];
    for (const group of groupedItems) {
      rows.push({ kind: "divider", id: `divider:${group.label}`, label: group.label });
      for (const block of group.blocks) {
        if (block.kind === "routine_group") {
          const containsUnread = Boolean(
            firstUnreadItemId
            && block.items.some(
              ({ anchorItem, childRuns }) =>
                anchorItem.id === firstUnreadItemId || childRuns.some((childRun) => childRun.id === firstUnreadItemId),
            ),
          );
          if (containsUnread) {
            rows.push({ kind: "unread", id: `unread:${block.id}` });
          }
          rows.push({ kind: "routine_group", id: block.id, block });
          continue;
        }
        if (
          firstUnreadItemId
          && (block.anchorItem.id === firstUnreadItemId || block.childRuns.some((childRun) => childRun.id === firstUnreadItemId))
        ) {
          rows.push({ kind: "unread", id: `unread:${block.anchorItem.id}` });
        }
        rows.push({
          kind: "item",
          id: `item:${block.anchorItem.id}`,
          item: block.anchorItem,
          childRuns: block.childRuns,
        });
      }
    }
    return rows;
  }, [groupedItems, firstUnreadItemId]);

  const rowIndexByStreamItemId = useMemo(() => {
    const indexMap = new Map<string, number>();
    timelineRows.forEach((row, index) => {
      if (row.kind === "item") {
        indexMap.set(row.item.id, index);
        row.childRuns.forEach((childRun) => indexMap.set(childRun.id, index));
        return;
      }
      if (row.kind === "routine_group") {
        row.block.items.forEach(({ anchorItem, childRuns }) => {
          indexMap.set(anchorItem.id, index);
          childRuns.forEach((childRun) => indexMap.set(childRun.id, index));
        });
      }
    });
    return indexMap;
  }, [timelineRows]);

  const rowIndexBySessionId = useMemo(() => {
    const indexMap = new Map<string, number>();
    timelineRows.forEach((row, index) => {
      if (row.kind === "item") {
        if (row.item.sessionId) {
          indexMap.set(row.item.sessionId, index);
        }
        row.childRuns.forEach((childRun) => indexMap.set(childRun.sessionId, index));
        return;
      }
      if (row.kind === "routine_group") {
        row.block.items.forEach(({ anchorItem, childRuns }) => {
          indexMap.set(anchorItem.sessionId, index);
          childRuns.forEach((childRun) => indexMap.set(childRun.sessionId, index));
        });
      }
    });
    return indexMap;
  }, [timelineRows]);

  const virtualizer = useVirtualizer({
    count: timelineRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => {
      const row = timelineRows[index];
      if (!row) {
        return 80;
      }
      if (row.kind === "divider") {
        return 56;
      }
      if (row.kind === "unread") {
        return 40;
      }
      if (row.kind === "routine_group") {
        return expandedRoutineGroupIds[row.block.id] ? 360 : 120;
      }
      const expanded = row.item.kind !== "message" && expandedEntryIds[row.item.id];
      const childRunCount = row.childRuns.length;
      return expanded ? 420 + childRunCount * 140 : 160 + childRunCount * 140;
    },
    overscan: 10,
  });

  const hasExpandedTimelineContent = useMemo(
    () =>
      Object.values(expandedEntryIds).some(Boolean)
      || Object.values(expandedRoutineGroupIds).some(Boolean),
    [expandedEntryIds, expandedRoutineGroupIds],
  );
  const virtualRows = virtualizer.getVirtualItems();
  const renderVirtualRows = false;
  const renderedRows = renderVirtualRows
    ? virtualRows.map((virtualRow) => ({
        key: virtualRow.key,
        row: timelineRows[virtualRow.index],
        start: virtualRow.start,
        measure: true,
      }))
    : timelineRows.map((row, index) => ({
        key: `${row.id}:${index}`,
        row,
        start: 0,
        measure: false,
      }));

  useEffect(() => {
    if (!focusSessionId) {
      return;
    }
    const rowIndex = rowIndexBySessionId.get(focusSessionId);
    if (rowIndex != null) {
      virtualizer.scrollToIndex(rowIndex, { align: "center" });
    }
    const timeout = window.setTimeout(() => {
      const nodes = document.querySelectorAll<HTMLElement>(`[data-session-anchor="${focusSessionId}"]`);
      const target = nodes.length > 0 ? nodes[nodes.length - 1] : null;
      target?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [entries, focusSessionId, rowIndexBySessionId, virtualizer]);

  const filterCounts = useMemo(() => {
    const counts: Record<FilterMode, number> = {
      all: hydratedEntries.length + messages.length,
      messages: [...hydratedEntries.filter((entry) => entry.entry_type === "message"), ...messages].length,
      work: hydratedEntries.filter((entry) => entry.entry_type === "heartbeat" || entry.entry_type === "child_run").length,
      heartbeats: hydratedEntries.filter((entry) => entry.entry_type === "heartbeat").length,
      friction: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "friction")).length,
      errors: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "error")).length,
      warnings: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "warning")).length,
      stalled: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "stalled")).length,
      drift: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "instruction_drift")).length,
      tool_friction: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "tool_friction")).length,
      retries: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "retries")).length,
      recovered: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "recovered")).length,
      escalations: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "escalation")).length,
    };
    return counts;
  }, [hydratedEntries, messages]);

  const newActivityCount = useMemo(() => {
    if (!firstUnreadItemId) {
      return 0;
    }
    const unreadIndex = mergedItems.findIndex((item) => item.id === firstUnreadItemId);
    if (unreadIndex < 0) {
      return 0;
    }
    return mergedItems.length - unreadIndex;
  }, [firstUnreadItemId, mergedItems]);

  const matchedIds = useMemo(() => new Set(searchMatches.map((item) => item.entry_id)), [searchMatches]);
  const activeSearchMatch = useMemo(
    () => searchMatches.findIndex((item) => item.entry_id === activeSearchMatchId),
    [activeSearchMatchId, searchMatches],
  );
  const activeMatchId = !deferredSearch.trim()
    ? null
    : activeSearchMatchId && searchMatches.some((item) => item.entry_id === activeSearchMatchId)
      ? activeSearchMatchId
      : searchMatches[0]?.entry_id ?? null;

  useEffect(() => {
    if (!deferredSearch.trim()) {
      setActiveSearchMatchId(null);
      return;
    }

    if (searchMatches.length === 0) {
      return;
    }
    if (!activeSearchMatchId || !searchMatches.some((item) => item.entry_id === activeSearchMatchId)) {
      setActiveSearchMatchId(searchMatches[0]?.entry_id ?? null);
    }
  }, [deferredSearch, searchMatches, activeSearchMatchId]);

  useEffect(() => {
    if (!activeMatchId) {
      return;
    }
    if (hydratedEntries.some((entry) => entry.id === activeMatchId && entry.entry_type !== "message")) {
      setExpandedEntryIds((current) => (
        current[activeMatchId]
          ? current
          : {
              ...current,
              [activeMatchId]: true,
            }
      ));
    }
    const loaded = mergedItems.some((item) => item.id === activeMatchId);
    if (!loaded && anchorEntryId !== activeMatchId) {
      setAnchorEntryId(activeMatchId);
      return;
    }
    const rowIndex = rowIndexByStreamItemId.get(activeMatchId);
    if (rowIndex != null) {
      virtualizer.scrollToIndex(rowIndex, { align: "center" });
    }
    const timeout = window.setTimeout(() => {
      const node = document.querySelector<HTMLElement>(`[data-stream-item-id="${activeMatchId}"]`);
      node?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [activeMatchId, mergedItems, anchorEntryId, rowIndexByStreamItemId, virtualizer]);

  const handleSessionJump = (sessionId: string | null) => {
    onSelectSession(sessionId);
    setFocusSessionId(sessionId);
    setAnchorEntryId(null);
    setAutoFollow(false);
  };

  const toggleExpanded = (entryId: string, sessionId?: string) => {
    const willExpand = !expandedEntryIds[entryId];
    if (willExpand && sessionId) {
      void loadSessionEventDetails(sessionId);
    }
    setExpandedEntryIds((current) => ({
      ...current,
      [entryId]: !current[entryId],
    }));
  };

  const toggleRoutineGroup = (groupId: string) => {
    setExpandedRoutineGroupIds((current) => ({
      ...current,
      [groupId]: !current[groupId],
    }));
  };

  const visibleSearchMatches = useMemo(() => {
    if (searchMatches.length === 0) {
      return [];
    }
    if (activeSearchMatch < 0) {
      return searchMatches.slice(0, 5);
    }
    const start = Math.max(activeSearchMatch - 2, 0);
    const end = Math.min(start + 5, searchMatches.length);
    return searchMatches.slice(Math.max(end - 5, 0), end);
  }, [searchMatches, activeSearchMatch]);

  const jumpToSearchMatch = (direction: 1 | -1) => {
    if (searchMatches.length === 0) {
      return;
    }
    const currentIndex = searchMatches.findIndex((item) => item.entry_id === activeMatchId);
    const fallbackIndex = 0;
    const resolvedIndex = currentIndex >= 0 ? currentIndex : fallbackIndex;

    const nextIndex = resolvedIndex + direction;
    if (nextIndex < 0) {
      setActiveSearchMatchId(searchMatches.at(-1)?.entry_id ?? null);
      setAnchorEntryId(searchMatches.at(-1)?.entry_id ?? null);
      setAutoFollow(false);
      return;
    }
    if (nextIndex >= searchMatches.length) {
      setActiveSearchMatchId(searchMatches[0]?.entry_id ?? null);
      setAnchorEntryId(searchMatches[0]?.entry_id ?? null);
      setAutoFollow(false);
      return;
    }
    setActiveSearchMatchId(searchMatches[nextIndex].entry_id);
    setAnchorEntryId(searchMatches[nextIndex].entry_id);
    setAutoFollow(false);
  };

  const visiblePulseMetrics = useMemo(
    () => pulse.metrics.filter((metric) => metric.count > 0 || metric.key === "friction"),
    [pulse.metrics],
  );
  const activeIssueTag = filterMode === "friction" ? "friction" : filterModeToPulseTag(filterMode);

  const applyPulseFilter = (nextMode: FilterMode, nextAnchorEntryId?: string | null) => {
    setFilterMode(nextMode);
    if (nextAnchorEntryId) {
      setAnchorEntryId(nextAnchorEntryId);
      setExpandedEntryIds((current) => ({ ...current, [nextAnchorEntryId]: true }));
      setAutoFollow(false);
    }
  };

  const inspectAgentPulse = (agentSlugValue: string) => {
    setFilterMode("friction");
    setSearch(`agent:${agentSlugValue}`);
    setAnchorEntryId(null);
    setAutoFollow(false);
  };

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <div className="flex flex-wrap items-center gap-2">
          <SessionDropdown
            activeSessionId={selectedSessionId}
            onSelectSession={handleSessionJump}
            onNewSession={onNewSession}
            projectId={PROJECT_ID}
            agentSlug={agentSlug}
            refreshTrigger={sidebarRefreshTrigger}
          />
          <div className="relative min-w-[18rem] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              id={searchInputId}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setAnchorEntryId(null);
              }}
              placeholder="Search Jenny's history, task IDs, files, agents..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm text-slate-700 outline-none transition focus:border-sky-300 focus:bg-white dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-700"
            />
          </div>
          <TimeRangeDropdown value={timeRange} onChange={setTimeRange} />
          <button
            type="button"
            onClick={() => {
              setAutoFollow((value) => {
                const next = !value;
                if (next) {
                  window.setTimeout(() => {
                    scrollToBottom("smooth");
                    setIsAtBottom(true);
                    markLatestAsRead();
                  }, 0);
                }
                return next;
              });
            }}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition",
              autoFollow
                ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-800"
                : "bg-slate-100 text-slate-600 ring-1 ring-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700",
            )}
          >
            <Radio className="h-4 w-4" />
            {autoFollow ? "Auto-follow on" : "Auto-follow off"}
          </button>
        </div>
        <div className="mt-2 text-[11px] text-slate-400 dark:text-slate-500">
          Search everything, or use prefixes like <span className="font-semibold">task:</span>, <span className="font-semibold">file:</span>, <span className="font-semibold">agent:</span>, <span className="font-semibold">status:</span>, and <span className="font-semibold">project:</span>.
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {([
            ["all", "All"],
            ["messages", "Messages"],
            ["work", "Work"],
            ["heartbeats", "Heartbeats"],
            ["friction", "Friction"],
            ["errors", "Errors"],
            ["warnings", "Warnings"],
            ["stalled", "Stalled"],
            ["drift", "Drift"],
            ["tool_friction", "Tool Friction"],
            ["retries", "Retries"],
            ["recovered", "Recovered"],
            ["escalations", "Escalations"],
          ] as Array<[FilterMode, string]>).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setFilterMode(value)}
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition",
                filterMode === value
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800",
              )}
            >
              {label}
              <span className="opacity-70">{filterCounts[value]}</span>
            </button>
          ))}
        </div>
        {deferredSearch.trim() && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
            <span>
              {matchCount === 0
                ? `No matches for "${deferredSearch.trim()}"`
                : `${Math.max(activeSearchMatch, 0) + 1} of ${matchCount} matches for "${deferredSearch.trim()}"`}
            </span>
            {matchCount > 0 && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => jumpToSearchMatch(-1)}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                  Prev match
                </button>
                <button
                  type="button"
                  onClick={() => jumpToSearchMatch(1)}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                  Next match
                </button>
              </div>
            )}
          </div>
        )}
        {deferredSearch.trim() && visibleSearchMatches.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {visibleSearchMatches.map((match) => (
              <button
                key={match.entry_id}
                type="button"
                onClick={() => {
                  setActiveSearchMatchId(match.entry_id);
                  setAnchorEntryId(match.entry_id);
                  setAutoFollow(false);
                }}
                className={cn(
                  "max-w-full rounded-2xl border px-3 py-2 text-left text-xs transition",
                  match.entry_id === activeMatchId
                    ? "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-100"
                    : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:bg-slate-900",
                )}
              >
                <div className="font-semibold uppercase tracking-[0.14em] text-[10px] opacity-70">
                  {formatTimeLabel(new Date(match.timestamp))} · {match.entry_type}
                </div>
                <HighlightedText text={shortenText(match.snippet, 90)} className="mt-1 block" />
              </button>
            ))}
          </div>
        )}
      </div>

      <div ref={scrollRef} data-testid="stream-scroll-container" className="flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto max-w-4xl">
          <PulseOverviewPanels
            visiblePulseMetrics={visiblePulseMetrics}
            pulse={pulse}
            applyPulseFilter={applyPulseFilter}
            inspectAgentPulse={inspectAgentPulse}
          />
        </div>

        {(error || chatError) && (
          <div className="mb-4 flex items-center gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300">
            <AlertCircle className="h-4 w-4" />
            {error || chatError}
          </div>
        )}

        {loading && entries.length === 0 ? (
          <div className="flex items-center justify-center py-20 text-slate-400">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : groupedItems.length === 0 ? (
          <div className="py-20 text-center text-slate-500 dark:text-slate-400">
            No stream entries yet.
          </div>
        ) : (
          <div className="mx-auto max-w-4xl">
            <div
              className="relative w-full"
              style={renderVirtualRows ? { height: `${virtualizer.getTotalSize()}px` } : undefined}
            >
              {renderedRows.map(({ key, row, start, measure }) => {
                if (!row) {
                  return null;
                }
                if (row.kind === "divider") {
                  return (
                    <div
                      key={key}
                      ref={measure ? virtualizer.measureElement : undefined}
                      className={cn(renderVirtualRows && "absolute left-0 top-0 w-full")}
                      style={renderVirtualRows ? { transform: `translateY(${start}px)` } : undefined}
                    >
                      <DateDivider label={row.label} />
                    </div>
                  );
                }
                if (row.kind === "unread") {
                  return (
                    <div
                      key={key}
                      ref={measure ? virtualizer.measureElement : undefined}
                      className={cn(renderVirtualRows && "absolute left-0 top-0 w-full")}
                      style={renderVirtualRows ? { transform: `translateY(${start}px)` } : undefined}
                    >
                      <div
                        data-testid="new-activity-separator"
                        className="flex items-center gap-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-sky-600 dark:text-sky-300"
                      >
                        <div className="h-px flex-1 bg-sky-200 dark:bg-sky-900" />
                        <span className="inline-flex items-center gap-1">
                          <CircleDot className="h-3.5 w-3.5" />
                          New since you scrolled away
                        </span>
                        <div className="h-px flex-1 bg-sky-200 dark:bg-sky-900" />
                      </div>
                    </div>
                  );
                }
                if (row.kind === "routine_group") {
                  return (
                    <div
                      key={key}
                      ref={measure ? virtualizer.measureElement : undefined}
                      className={cn(renderVirtualRows && "absolute left-0 top-0 w-full")}
                      style={renderVirtualRows ? { transform: `translateY(${start}px)` } : undefined}
                    >
                      <RoutineHeartbeatGroup
                        block={row.block}
                        expanded={!!expandedRoutineGroupIds[row.block.id]}
                        onToggle={() => toggleRoutineGroup(row.block.id)}
                        activeSessionId={selectedSessionId}
                        activeIssueTag={activeIssueTag}
                        expandedEntryIds={expandedEntryIds}
                        onToggleEntry={toggleExpanded}
                        sessionEventDetails={sessionEventDetails}
                      />
                    </div>
                  );
                }

                const item = row.item;
                const selected = !!item.sessionId && item.sessionId === selectedSessionId;
                const matched = matchedIds.has(item.id);
                const activeMatched = activeMatchId === item.id;
                const baseClasses = cn(
                  "flex items-start gap-3 rounded-2xl",
                  matched && "px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
                  activeMatched && "ring-2 ring-amber-400 dark:ring-amber-500",
                );

                return (
                  <div
                    key={key}
                    ref={measure ? virtualizer.measureElement : undefined}
                    className={cn(renderVirtualRows && "absolute left-0 top-0 w-full")}
                    style={renderVirtualRows ? { transform: `translateY(${start}px)` } : undefined}
                  >
                    {item.kind === "message" ? (
                      <div
                        data-session-anchor={item.sessionId ?? undefined}
                        data-testid="stream-item"
                        data-stream-item-id={item.id}
                        data-timestamp={item.timestamp.toISOString()}
                        className={cn(
                          "flex items-start gap-3",
                          selected && "rounded-2xl bg-sky-50/40 px-2 py-1 dark:bg-sky-950/10",
                          matched && "rounded-2xl px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
                          activeMatched && "ring-2 ring-amber-400 dark:ring-amber-500",
                        )}
                      >
                        <TimelineTimestamp timestamp={item.timestamp} />
                        <div className="min-w-0 flex-1">
                          <MessageBubble
                            message={item.message}
                            isStreaming={status !== "idle" && status !== "error"}
                            canEdit={false}
                            canRegenerate={false}
                          />
                          {row.childRuns.length > 0 && (
                            <ChildRunStack
                              childRuns={row.childRuns}
                              activeSessionId={selectedSessionId}
                              activeIssueTag={activeIssueTag}
                              expandedEntryIds={expandedEntryIds}
                              onToggle={toggleExpanded}
                              matchedIds={matchedIds}
                              activeMatchId={activeMatchId}
                              sessionEventDetails={sessionEventDetails}
                            />
                          )}
                        </div>
                      </div>
                    ) : item.kind === "child_run" ? (
                      <div
                        data-session-anchor={item.sessionId}
                        data-testid="stream-item"
                        data-stream-item-id={item.id}
                        data-timestamp={item.timestamp.toISOString()}
                        className={baseClasses}
                      >
                        <TimelineTimestamp timestamp={item.timestamp} />
                        <div className="min-w-0 flex-1">
                          <ChildRunCard
                            entry={item.entry}
                            activeIssueTag={activeIssueTag}
                            selected={selected}
                            expanded={!!expandedEntryIds[item.id]}
                            onToggle={() => toggleExpanded(item.id, item.sessionId)}
                            details={sessionEventDetails[item.sessionId]}
                          />
                        </div>
                      </div>
                    ) : (
                      <div
                        data-session-anchor={item.sessionId}
                        data-testid="stream-item"
                        data-stream-item-id={item.id}
                        data-timestamp={item.timestamp.toISOString()}
                        className={baseClasses}
                      >
                        <TimelineTimestamp timestamp={item.timestamp} />
                        <div className="min-w-0 flex-1">
                          <HeartbeatCard
                            entry={item.entry}
                            activeIssueTag={activeIssueTag}
                            selected={selected}
                            expanded={!!expandedEntryIds[item.id]}
                            onToggle={() => toggleExpanded(item.id, item.sessionId)}
                            details={sessionEventDetails[item.sessionId]}
                          />
                          {row.childRuns.length > 0 && (
                            <ChildRunStack
                              childRuns={row.childRuns}
                              activeSessionId={selectedSessionId}
                              activeIssueTag={activeIssueTag}
                              expandedEntryIds={expandedEntryIds}
                              onToggle={toggleExpanded}
                              matchedIds={matchedIds}
                              activeMatchId={activeMatchId}
                              sessionEventDetails={sessionEventDetails}
                            />
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {total > entries.length && !deferredSearch.trim() && (
              <div className="flex justify-center pt-6">
                <button
                  onClick={() => {
                    const container = scrollRef.current;
                    if (container) {
                      olderHistoryAnchorRef.current = {
                        scrollHeight: container.scrollHeight,
                        scrollTop: container.scrollTop,
                      };
                    }
                    setPage((value) => value + 1);
                  }}
                  className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600 transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  Load older entries
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {(latestItemId && (!isAtBottom || !autoFollow || newActivityCount > 0)) && (
        <div className="pointer-events-none absolute bottom-24 right-6 z-20">
          <button
            type="button"
            onClick={() => {
              setAutoFollow(true);
              scrollToBottom("smooth");
              setIsAtBottom(true);
              markLatestAsRead();
            }}
            className="pointer-events-auto inline-flex items-center gap-2 rounded-full bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-lg transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
          >
            <ArrowDown className="h-4 w-4" />
            {newActivityCount > 0 ? `${newActivityCount} new ${newActivityCount === 1 ? "item" : "items"} · Jump to latest` : "Jump to latest"}
          </button>
        </div>
      )}

      <div className="border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95">
        <div className="mx-auto max-w-4xl">
          <div className="mb-2 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <span className="inline-flex items-center gap-1">
              <Sparkles className="h-3.5 w-3.5" />
              Composer is attached to {activeSessionId ? `session ${activeSessionId.slice(0, 8)}` : "a new thread"}
            </span>
            {status !== "idle" && (
              <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-300">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Jenny is responding
              </span>
            )}
          </div>
          <MessageInput
            onSend={sendMessage}
            onCancel={cancelStream}
            status={status}
            voiceWsUrl={getWsUrl("/api/voice/ws?user_id=agent_hub_user&app=agent-hub&mode=transcribe")}
            ttsBaseUrl={getApiBaseUrl() || window.location.origin}
            preferencesEndpoint={apiConfig.preferencesEndpoint}
            fetchFn={fetchApi}
          />
        </div>
      </div>
    </div>
  );
}
