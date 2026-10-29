import type { ToolDiff } from "./tool-format";
import { BAD, OK, tint } from "./colors";

/** Lines shown before the rest is folded into a count; a pasted file is not worth a screen. */
const MAX_LINES = 120;

/** An inline diff: file name and +n -m on a header, then the lines with a sign column. */
export function DiffBlock({ diff }: { diff: ToolDiff }) {
  const shown = diff.lines.slice(0, MAX_LINES);
  const hidden = diff.lines.length - shown.length;
  return (
    <div
      data-testid="tool-diff"
      role="group"
      aria-label={diff.file ? `Changes to ${diff.file}` : "Changes"}
      className="mt-1 ml-4 overflow-hidden rounded-md border border-border font-mono text-[12px] leading-[1.55]"
    >
      <div className="flex items-center justify-between gap-3 bg-muted px-2.5 py-1 text-muted-foreground">
        <span className="min-w-0 truncate" data-testid="diff-file">
          {diff.file || "changes"}
        </span>
        <span className="shrink-0 tabular-nums" data-testid="diff-counts">
          <span style={{ color: OK }}>+{diff.added}</span> <span style={{ color: BAD }}>{"−"}{diff.removed}</span>
        </span>
      </div>
      <pre className="m-0 overflow-x-auto py-1.5">
        {shown.map((line, index) => (
          <span
            key={index}
            data-diff={line.kind}
            className="block whitespace-pre px-2.5"
            style={
              line.kind === "add"
                ? { backgroundColor: tint(OK, 10), color: `color-mix(in oklab, ${OK} 70%, var(--foreground, #e7e2d6))` }
                : line.kind === "del"
                  ? { backgroundColor: tint(BAD, 11), color: `color-mix(in oklab, ${BAD} 70%, var(--foreground, #e7e2d6))` }
                  : undefined
            }
          >
            <span aria-hidden className="inline-block w-4 select-none opacity-70">
              {line.kind === "add" ? "+" : line.kind === "del" ? "−" : " "}
            </span>
            {line.text || " "}
          </span>
        ))}
        {hidden > 0 ? (
          <span className="block px-2.5 pt-1 text-muted-foreground">
            {"…"} {hidden} more {hidden === 1 ? "line" : "lines"}
          </span>
        ) : null}
      </pre>
    </div>
  );
}
