import type { PersonaIssueMarker, PersonaStreamEntry } from "@/lib/api/persona-stream";

export type FilterMode =
  | "all"
  | "messages"
  | "work"
  | "heartbeats"
  | "friction"
  | "errors"
  | "warnings"
  | "stalled"
  | "drift"
  | "tool_friction"
  | "retries"
  | "recovered"
  | "escalations";

const FILTER_TAG_MAP: Record<Exclude<FilterMode, "all" | "messages" | "work" | "heartbeats">, string> = {
  friction: "friction",
  errors: "error",
  warnings: "warning",
  stalled: "stalled",
  drift: "instruction_drift",
  tool_friction: "tool_friction",
  retries: "retries",
  recovered: "recovered",
  escalations: "escalation",
};

export function filterModeToPulseTag(mode: FilterMode): string | null {
  if (mode in FILTER_TAG_MAP) {
    return FILTER_TAG_MAP[mode as keyof typeof FILTER_TAG_MAP];
  }
  return null;
}

export function pulseTagToFilterMode(tag: string): FilterMode {
  switch (tag) {
    case "friction":
      return "friction";
    case "error":
      return "errors";
    case "warning":
      return "warnings";
    case "stalled":
      return "stalled";
    case "instruction_drift":
      return "drift";
    case "tool_friction":
      return "tool_friction";
    case "retries":
      return "retries";
    case "recovered":
      return "recovered";
    case "escalation":
      return "escalations";
    default:
      return "all";
  }
}

export function pulseTagLabel(tag: string): string {
  switch (tag) {
    case "friction":
      return "Friction";
    case "error":
      return "Error";
    case "warning":
      return "Warning";
    case "stalled":
      return "Stalled";
    case "retries":
      return "Retries";
    case "instruction_drift":
      return "Instruction Drift";
    case "tool_friction":
      return "Tool Friction";
    case "recovered":
      return "Recovered";
    case "escalation":
      return "Escalation";
    default:
      return tag.replaceAll("_", " ");
  }
}

export function rootCauseLabel(rootCause: string): string {
  switch (rootCause) {
    case "workflow":
      return "Workflow";
    case "tool":
      return "Tool";
    case "context":
      return "Context";
    case "infra":
      return "Infra";
    case "prompt":
      return "Prompt";
    default:
      return "Unknown";
  }
}

export function pulseTagClasses(tag: string): string {
  switch (tag) {
    case "friction":
      return "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900";
    case "error":
      return "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300";
    case "warning":
    case "stalled":
    case "escalation":
      return "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300";
    case "instruction_drift":
      return "bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-950/40 dark:text-fuchsia-300";
    case "tool_friction":
    case "retries":
      return "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300";
    case "recovered":
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300";
    default:
      return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";
  }
}

export function entryHasPulseTag(entry: PersonaStreamEntry, tag: string): boolean {
  if (tag === "friction") {
    return entry.issue_markers.length > 0 || entry.pulse_tags.includes("friction");
  }
  if (tag === "recovered") {
    return entry.pulse_tags.includes("recovered");
  }
  if (entry.issue_markers.some((marker) => marker.tags.includes(tag))) {
    return true;
  }
  return entry.pulse_tags.includes(tag);
}

export function issueMarkerHasPulseTag(marker: PersonaIssueMarker, tag: string): boolean {
  if (tag === "friction") {
    return true;
  }
  return marker.tags.includes(tag);
}

export function filterIssueMarkers(issueMarkers: PersonaIssueMarker[], tag: string | null): PersonaIssueMarker[] {
  if (!tag || tag === "recovered") {
    return issueMarkers;
  }
  return issueMarkers.filter((marker) => issueMarkerHasPulseTag(marker, tag));
}

export function visibleIssueMarkers(entry: PersonaStreamEntry, tag: string | null): PersonaIssueMarker[] {
  return filterIssueMarkers(entry.issue_markers, tag);
}
