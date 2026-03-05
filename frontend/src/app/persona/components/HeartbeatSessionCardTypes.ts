export interface EventPreview {
  event_type: string;
  tool_name: string | null;
  content_preview: string | null;
}

export interface SessionEvent {
  id: string;
  turn: number;
  sequence: number;
  event_type: string;
  role: string | null;
  content: string | null;
  tool_name: string | null;
  tool_input: Record<string, unknown> | null;
  tool_output: Record<string, unknown> | null;
  tokens: number | null;
  duration_ms: number | null;
  created_at: string;
}

export interface HeartbeatSessionCardProps {
  id: string;
  summary: string | null;
  status: string;
  messageCount: number;
  createdAt: string;
  eventsPreview: EventPreview[];
}

/* ── Tool Category System ─────────────────────────── */

export const CATEGORY_STYLES = {
  memory: {
    dot: "bg-violet-400 ring-violet-500/20",
    badge: "bg-violet-500/10 border-violet-500/20 text-violet-400",
  },
  schedule: {
    dot: "bg-blue-400 ring-blue-500/20",
    badge: "bg-blue-500/10 border-blue-500/20 text-blue-400",
  },
  system: {
    dot: "bg-amber-400 ring-amber-500/20",
    badge: "bg-amber-500/10 border-amber-500/20 text-amber-400",
  },
  file: {
    dot: "bg-emerald-400 ring-emerald-500/20",
    badge: "bg-emerald-500/10 border-emerald-500/20 text-emerald-400",
  },
  search: {
    dot: "bg-cyan-400 ring-cyan-500/20",
    badge: "bg-cyan-500/10 border-cyan-500/20 text-cyan-400",
  },
  default: {
    dot: "bg-slate-400 ring-slate-500/20",
    badge: "bg-slate-500/10 border-slate-500/20 text-slate-400",
  },
} as const;

export type ToolCategory = keyof typeof CATEGORY_STYLES;

export function getToolCategory(toolName: string | null): ToolCategory {
  if (!toolName) return "default";
  const name = toolName.toLowerCase();
  if (name.includes("memory")) return "memory";
  if (name.includes("schedule") || name.includes("cron")) return "schedule";
  if (name === "bash" || name.includes("service") || name.includes("health"))
    return "system";
  if (["read", "write", "edit", "glob"].includes(name)) return "file";
  if (["grep", "websearch", "webfetch"].includes(name)) return "search";
  return "default";
}
