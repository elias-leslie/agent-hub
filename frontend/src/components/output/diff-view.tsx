"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { Minus, Plus, FileCode2 } from "lucide-react";

interface DiffLine {
  type: "add" | "remove" | "context";
  content: string;
  oldLineNumber?: number;
  newLineNumber?: number;
}

interface DiffViewProps {
  diff: string;
  filename?: string;
  className?: string;
  maxHeight?: number;
}

function parseDiff(diff: string): DiffLine[] {
  const lines = diff.split("\n");
  const result: DiffLine[] = [];
  let oldLine = 1;
  let newLine = 1;

  for (const line of lines) {
    // Skip diff headers
    if (
      line.startsWith("diff ") ||
      line.startsWith("index ") ||
      line.startsWith("---") ||
      line.startsWith("+++")
    ) {
      continue;
    }

    // Parse hunk headers for line numbers
    const hunkMatch = line.match(/^@@\s*-(\d+)(?:,\d+)?\s*\+(\d+)(?:,\d+)?\s*@@/);
    if (hunkMatch) {
      oldLine = parseInt(hunkMatch[1], 10);
      newLine = parseInt(hunkMatch[2], 10);
      continue;
    }

    if (line.startsWith("+")) {
      result.push({
        type: "add",
        content: line.slice(1),
        newLineNumber: newLine++,
      });
    } else if (line.startsWith("-")) {
      result.push({
        type: "remove",
        content: line.slice(1),
        oldLineNumber: oldLine++,
      });
    } else if (line.startsWith(" ") || line === "") {
      result.push({
        type: "context",
        content: line.startsWith(" ") ? line.slice(1) : line,
        oldLineNumber: oldLine++,
        newLineNumber: newLine++,
      });
    }
  }

  return result;
}

export function DiffView({ diff, filename, className, maxHeight = 400 }: DiffViewProps) {
  const lines = useMemo(() => parseDiff(diff), [diff]);

  const stats = useMemo(() => {
    const additions = lines.filter((l) => l.type === "add").length;
    const deletions = lines.filter((l) => l.type === "remove").length;
    return { additions, deletions };
  }, [lines]);

  return (
    <div
      className={cn(
        "rounded-lg overflow-hidden font-mono text-sm",
        "bg-[oklch(0.12_0_0)] dark:bg-[oklch(0.08_0_0)]",
        "border border-[oklch(0.25_0_0)] dark:border-[oklch(0.2_0_0)]",
        "shadow-[0_2px_8px_oklch(0_0_0/0.15)] dark:shadow-[0_2px_12px_oklch(0_0_0/0.4)]",
        className
      )}
    >
      {/* Header */}
      <div
        className={cn(
          "flex items-center justify-between px-3 py-2",
          "bg-[oklch(0.16_0_0)] dark:bg-[oklch(0.1_0_0)]",
          "border-b border-[oklch(0.25_0_0)] dark:border-[oklch(0.18_0_0)]"
        )}
      >
        <div className="flex items-center gap-2">
          <FileCode2 className="w-4 h-4 text-[oklch(0.6_0_0)]" />
          {filename && (
            <span className="text-xs font-medium text-[oklch(0.7_0_0)]">{filename}</span>
          )}
          {!filename && (
            <span className="text-xs font-medium tracking-wider uppercase text-[oklch(0.55_0_0)]">
              Diff
            </span>
          )}
        </div>

        <div className="flex items-center gap-3 text-xs font-medium">
          <span className="flex items-center gap-1 text-[oklch(0.65_0.15_145)]">
            <Plus className="w-3 h-3" />
            {stats.additions}
          </span>
          <span className="flex items-center gap-1 text-[oklch(0.65_0.15_25)]">
            <Minus className="w-3 h-3" />
            {stats.deletions}
          </span>
        </div>
      </div>

      {/* Diff content */}
      <div className="overflow-auto" style={{ maxHeight }}>
        <table className="w-full border-collapse">
          <tbody>
            {lines.map((line, index) => (
              <tr
                key={index}
                className={cn(
                  "group",
                  line.type === "add" &&
                    "bg-[oklch(0.25_0.08_145/0.2)] dark:bg-[oklch(0.2_0.08_145/0.15)]",
                  line.type === "remove" &&
                    "bg-[oklch(0.25_0.1_25/0.2)] dark:bg-[oklch(0.2_0.1_25/0.15)]"
                )}
              >
                {/* Old line number */}
                <td
                  className={cn(
                    "w-10 px-2 py-0 text-right text-xs select-none",
                    "border-r border-[oklch(0.22_0_0)] dark:border-[oklch(0.16_0_0)]",
                    "text-[oklch(0.45_0_0)]",
                    line.type === "add" && "bg-[oklch(0.2_0.05_145/0.3)]",
                    line.type === "remove" && "bg-[oklch(0.2_0.06_25/0.3)]"
                  )}
                >
                  {line.type !== "add" ? line.oldLineNumber : ""}
                </td>

                {/* New line number */}
                <td
                  className={cn(
                    "w-10 px-2 py-0 text-right text-xs select-none",
                    "border-r border-[oklch(0.22_0_0)] dark:border-[oklch(0.16_0_0)]",
                    "text-[oklch(0.45_0_0)]",
                    line.type === "add" && "bg-[oklch(0.2_0.05_145/0.3)]",
                    line.type === "remove" && "bg-[oklch(0.2_0.06_25/0.3)]"
                  )}
                >
                  {line.type !== "remove" ? line.newLineNumber : ""}
                </td>

                {/* Change indicator */}
                <td
                  className={cn(
                    "w-6 text-center select-none font-bold",
                    line.type === "add" && "text-[oklch(0.65_0.18_145)]",
                    line.type === "remove" && "text-[oklch(0.65_0.18_25)]"
                  )}
                >
                  {line.type === "add" && "+"}
                  {line.type === "remove" && "-"}
                </td>

                {/* Content */}
                <td
                  className={cn(
                    "px-3 py-0.5 whitespace-pre",
                    line.type === "context" && "text-[oklch(0.75_0_0)]",
                    line.type === "add" && "text-[oklch(0.8_0.08_145)]",
                    line.type === "remove" && "text-[oklch(0.75_0.08_25)]"
                  )}
                >
                  {line.content}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Inline diff for showing word-level changes
interface InlineDiffProps {
  oldText: string;
  newText: string;
  className?: string;
}

export function InlineDiff({ oldText, newText, className }: InlineDiffProps) {
  return (
    <div className={cn("space-y-1 font-mono text-sm", className)}>
      <div className="flex items-start gap-2">
        <span className="flex-shrink-0 w-5 h-5 rounded flex items-center justify-center bg-[oklch(0.3_0.1_25/0.3)] text-[oklch(0.65_0.15_25)]">
          <Minus className="w-3 h-3" />
        </span>
        <span className="line-through text-[oklch(0.6_0.08_25)] bg-[oklch(0.25_0.08_25/0.15)] px-1 rounded">
          {oldText}
        </span>
      </div>
      <div className="flex items-start gap-2">
        <span className="flex-shrink-0 w-5 h-5 rounded flex items-center justify-center bg-[oklch(0.3_0.1_145/0.3)] text-[oklch(0.65_0.15_145)]">
          <Plus className="w-3 h-3" />
        </span>
        <span className="text-[oklch(0.75_0.08_145)] bg-[oklch(0.25_0.08_145/0.15)] px-1 rounded">
          {newText}
        </span>
      </div>
    </div>
  );
}
