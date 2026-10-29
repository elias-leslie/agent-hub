/**
 * How the transcript layout names a tool call, summarises its arguments and diffs an edit. Pure functions: the
 * components only draw what these return.
 */

import type { ToolExecution } from "../../types/chat";

export type ToolKind = "read" | "edit" | "write" | "bash" | "search" | "fetch" | "other";

export interface ToolLabel {
  kind: ToolKind;
  /** The name shown on the line: Read, Edit, Write, Bash, Search, Fetch, else the raw tool name. */
  name: string;
  /** The arguments in a few words: a path, a command, a query. Empty when there is nothing worth showing. */
  summary: string;
}

const KIND_BY_NAME: Record<string, ToolKind> = {
  read: "read",
  read_file: "read",
  readfile: "read",
  view: "read",
  cat: "read",
  open_file: "read",
  edit: "edit",
  edit_file: "edit",
  editfile: "edit",
  multiedit: "edit",
  multi_edit: "edit",
  str_replace: "edit",
  str_replace_editor: "edit",
  str_replace_based_edit_tool: "edit",
  replace: "edit",
  patch: "edit",
  write: "write",
  write_file: "write",
  writefile: "write",
  create_file: "write",
  create: "write",
  bash: "bash",
  shell: "bash",
  sh: "bash",
  exec: "bash",
  exec_command: "bash",
  run_command: "bash",
  run_shell_command: "bash",
  execute_command: "bash",
  grep: "search",
  glob: "search",
  find: "search",
  rg: "search",
  ripgrep: "search",
  search: "search",
  search_files: "search",
  search_code: "search",
  search_web: "search",
  web_search: "search",
  research_web: "search",
  search_scratch_context: "search",
  list_files: "search",
  ls: "search",
  fetch: "fetch",
  fetch_url: "fetch",
  fetch_web_page: "fetch",
  web_fetch: "fetch",
  webfetch: "fetch",
};

const DISPLAY: Record<Exclude<ToolKind, "other">, string> = {
  read: "Read",
  edit: "Edit",
  write: "Write",
  bash: "Bash",
  search: "Search",
  fetch: "Fetch",
};

const SUMMARY_MAX = 120;

/** `mcp__server__read_file` and `functions.read_file` both name the tool `read_file`. */
export function bareToolName(name: string): string {
  const tail = name.split(/__|\./).filter(Boolean).pop() ?? name;
  return tail.trim();
}

export function toolKind(name: string): ToolKind {
  return KIND_BY_NAME[bareToolName(name).toLowerCase()] ?? "other";
}

function str(input: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number") return String(value);
  }
  return undefined;
}

function num(input: Record<string, unknown>, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = input[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && /^\d+$/.test(value)) return Number(value);
  }
  return undefined;
}

function clip(text: string, max = SUMMARY_MAX): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

export function lineCount(text: string): number {
  if (!text) return 0;
  return text.replace(/\n$/, "").split("\n").length;
}

const PATH_KEYS = ["path", "file_path", "filePath", "file", "filename", "target_file"] as const;

function pathOf(input: Record<string, unknown>): string | undefined {
  return str(input, ...PATH_KEYS);
}

/** "lines 30-60" from an offset (0-based, as Agent Hub's read_file takes it) and a limit, or start/end lines. */
function readRange(input: Record<string, unknown>): string | undefined {
  const start = num(input, "start_line", "startLine", "line_start");
  const end = num(input, "end_line", "endLine", "line_end");
  if (start !== undefined && end !== undefined) return `lines ${start}–${end}`;
  const offset = num(input, "offset");
  const limit = num(input, "limit");
  if (offset !== undefined && limit !== undefined) return `lines ${offset + 1}–${offset + limit}`;
  if (offset !== undefined && offset > 0) return `from line ${offset + 1}`;
  if (limit !== undefined) return `first ${limit} lines`;
  return undefined;
}

/** The first plain argument of an unknown tool, else a compact JSON of all of them. */
function genericSummary(input: Record<string, unknown>): string {
  const entries = Object.entries(input);
  if (entries.length === 0) return "";
  const first = entries.find(([, value]) => typeof value === "string" && value.trim());
  if (first) return clip(String(first[1]));
  return clip(JSON.stringify(input));
}

/** Name and argument summary of one call. */
export function describeTool(tool: Pick<ToolExecution, "name" | "input">): ToolLabel {
  const input = tool.input ?? {};
  const kind = toolKind(tool.name);
  if (kind === "other") return { kind, name: bareToolName(tool.name) || tool.name, summary: genericSummary(input) };
  const name = DISPLAY[kind];
  switch (kind) {
    case "read": {
      const path = pathOf(input);
      const range = readRange(input);
      return { kind, name, summary: [path, range].filter(Boolean).join(" · ") || genericSummary(input) };
    }
    case "edit": {
      const path = pathOf(input);
      return { kind, name, summary: path ?? genericSummary(input) };
    }
    case "write": {
      const path = pathOf(input);
      const content = str(input, "content", "text", "file_text", "contents");
      const lines = content !== undefined ? lineCount(content) : undefined;
      return {
        kind,
        name,
        summary: [path, lines !== undefined ? `${lines} ${lines === 1 ? "line" : "lines"}` : undefined].filter(Boolean).join(" · ") || genericSummary(input),
      };
    }
    case "bash": {
      const command = str(input, "command", "cmd", "script");
      return { kind, name, summary: command ? clip(command) : genericSummary(input) };
    }
    case "search": {
      const pattern = str(input, "pattern", "query", "q", "regex", "search", "glob");
      const where = str(input, "path", "directory", "dir", "cwd");
      const quoted = pattern ? `"${clip(pattern, 80)}"` : undefined;
      const shownWhere = where ? (pattern ? `in ${clip(where, 60)}` : clip(where, 60)) : undefined;
      return { kind, name, summary: [quoted, shownWhere].filter(Boolean).join(" ") || genericSummary(input) };
    }
    case "fetch": {
      const url = str(input, "url", "uri", "href");
      return { kind, name, summary: url ? clip(url) : genericSummary(input) };
    }
  }
}

export interface DiffLine {
  kind: "context" | "add" | "del";
  text: string;
}

export interface ToolDiff {
  /** The file the call changes; empty when the arguments do not say. */
  file: string;
  lines: DiffLine[];
  added: number;
  removed: number;
}

/** Longest-common-subsequence line diff of two small texts. Larger inputs fall back to "all out, all in". */
export function diffLines(before: string, after: string): DiffLine[] {
  const a = before === "" ? [] : before.replace(/\n$/, "").split("\n");
  const b = after === "" ? [] : after.replace(/\n$/, "").split("\n");
  // Equal heads and tails first: the common case for an edit is a few changed lines in a larger block.
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head++;
  let tail = 0;
  while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail++;
  const midA = a.slice(head, a.length - tail);
  const midB = b.slice(head, b.length - tail);
  const out: DiffLine[] = a.slice(0, head).map((text) => ({ kind: "context" as const, text }));

  if (midA.length * midB.length > 250_000) {
    out.push(...midA.map((text) => ({ kind: "del" as const, text })), ...midB.map((text) => ({ kind: "add" as const, text })));
  } else {
    const n = midA.length;
    const m = midB.length;
    const table: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        table[i][j] = midA[i] === midB[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (midA[i] === midB[j]) {
        out.push({ kind: "context", text: midA[i] });
        i++;
        j++;
      } else if (table[i + 1][j] >= table[i][j + 1]) {
        out.push({ kind: "del", text: midA[i++] });
      } else {
        out.push({ kind: "add", text: midB[j++] });
      }
    }
    while (i < n) out.push({ kind: "del", text: midA[i++] });
    while (j < m) out.push({ kind: "add", text: midB[j++] });
  }
  out.push(...a.slice(a.length - tail).map((text) => ({ kind: "context" as const, text })));
  return out;
}

function countKinds(lines: DiffLine[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const line of lines) {
    if (line.kind === "add") added++;
    else if (line.kind === "del") removed++;
  }
  return { added, removed };
}

const OLD_KEYS = ["old_text", "old_string", "oldText", "oldString", "old_str", "old"] as const;
const NEW_KEYS = ["new_text", "new_string", "newText", "newString", "new_str", "new"] as const;

function pair(entry: Record<string, unknown>): { before: string; after: string } | null {
  const before = OLD_KEYS.map((key) => entry[key]).find((value) => typeof value === "string") as string | undefined;
  const after = NEW_KEYS.map((key) => entry[key]).find((value) => typeof value === "string") as string | undefined;
  if (before === undefined || after === undefined) return null;
  return { before, after };
}

/**
 * The diff an Edit or Write call makes, worked out from its arguments alone (old and new text, or the written
 * content as all additions). Null for any other call, or when the arguments carry no text to compare.
 */
export function diffForTool(tool: Pick<ToolExecution, "name" | "input">): ToolDiff | null {
  const kind = toolKind(tool.name);
  const input = tool.input ?? {};
  const file = pathOf(input) ?? "";
  if (kind === "edit") {
    const edits = Array.isArray(input.edits) ? (input.edits as unknown[]) : null;
    const pairs = (edits ?? [input])
      .map((entry) => (entry && typeof entry === "object" ? pair(entry as Record<string, unknown>) : null))
      .filter((entry): entry is { before: string; after: string } => entry !== null);
    if (pairs.length === 0) return null;
    const lines: DiffLine[] = [];
    pairs.forEach((entry, index) => {
      if (index > 0) lines.push({ kind: "context", text: "…" });
      lines.push(...diffLines(entry.before, entry.after));
    });
    return { file, lines, ...countKinds(lines) };
  }
  if (kind === "write") {
    const content = str(input, "content", "text", "file_text", "contents");
    if (content === undefined) return null;
    const lines = content === "" ? [] : content.replace(/\n$/, "").split("\n").map((text) => ({ kind: "add" as const, text }));
    return { file, lines, ...countKinds(lines) };
  }
  return null;
}

/** "18.2k" for 18,230; whole numbers below a thousand. */
export function compactCount(value: number): string {
  if (value < 1000) return String(Math.round(value));
  if (value < 10_000) return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  if (value < 1_000_000) return `${Math.round(value / 1000)}k`;
  return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}m`;
}

/** "$0.002" for small amounts, "$1.24" from a cent up. */
export function formatUsd(cost: number): string {
  if (cost < 0.01) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
}

/** "8s", "1m 12s". */
export function formatSeconds(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
