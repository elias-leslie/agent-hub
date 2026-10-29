import { useEffect, useState } from "react";
import type { ToolExecution } from "../../types/chat";
import { cn } from "../../lib/utils";
import { BAD, OK, WORK } from "./colors";
import { DiffBlock } from "./DiffBlock";
import { describeTool, diffForTool, formatSeconds } from "./tool-format";

/** Output longer than this is cut; the full text is in the session. */
const OUTPUT_MAX = 4000;

/** The current time, ticking every second while `active`. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

const STATUS_WORD = { running: "running", complete: "done", error: "failed" } as const;

/**
 * One tool call as one mono line: a status dot, the tool's name, its arguments in a few words. Clicking opens the
 * output in an indented block with a left rule. An edit shows its diff at once; a call that failed shows why.
 */
export function ToolLine({ tool }: { tool: ToolExecution }) {
  const label = describeTool(tool);
  const diff = diffForTool(tool);
  const running = tool.status === "running";
  const now = useNow(running);
  const [chosen, setChosen] = useState<boolean | null>(null);
  const openByDefault = label.kind === "edit" || tool.status === "error" || (running && label.kind === "bash");
  const open = chosen ?? openByDefault;
  const seconds = running ? Math.max(0, Math.floor((now - tool.startedAt.getTime()) / 1000)) : 0;
  const result = tool.result ?? "";
  const shownResult = result.length > OUTPUT_MAX ? result.slice(0, OUTPUT_MAX) : result;
  const hiddenChars = result.length - shownResult.length;
  const color = tool.status === "error" ? BAD : running ? WORK : OK;

  return (
    <div data-testid="tool-line" data-status={tool.status} data-kind={label.kind} className="font-mono text-[13px] leading-[1.45]">
      <button
        type="button"
        onClick={() => setChosen(!open)}
        aria-expanded={open}
        className="flex w-full min-w-0 items-baseline gap-2 rounded-sm text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        <span
          aria-hidden
          data-testid="tool-dot"
          className={cn("inline-block h-2 w-2 shrink-0 -translate-y-px rounded-full", running && "animate-pulse motion-reduce:animate-none")}
          style={{ backgroundColor: color }}
        />
        <span className="sr-only">{STATUS_WORD[tool.status]}: </span>
        <span className="shrink-0 font-semibold text-foreground">{label.name}</span>
        {label.summary ? <span className="min-w-0 truncate text-muted-foreground">{label.summary}</span> : null}
      </button>

      {open ? (
        <>
          {diff ? <DiffBlock diff={diff} /> : null}
          {running && label.kind === "bash" ? (
            <div data-testid="tool-output" className="ml-4 mt-1 border-l border-border pl-3 text-muted-foreground">
              running{"…"} {formatSeconds(seconds)}
            </div>
          ) : !diff || tool.status === "error" || result ? (
            <ToolOutput text={shownResult} hiddenChars={hiddenChars} empty={!running && !result} />
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function ToolOutput({ text, hiddenChars, empty }: { text: string; hiddenChars: number; empty: boolean }) {
  if (empty) {
    return (
      <div data-testid="tool-output" className="ml-4 mt-1 border-l border-border pl-3 text-muted-foreground">
        No output
      </div>
    );
  }
  if (!text) return null;
  return (
    <pre
      data-testid="tool-output"
      className="m-0 ml-4 mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words border-l border-border pl-3 text-[12.5px] text-muted-foreground"
    >
      {text}
      {hiddenChars > 0 ? `\n… ${hiddenChars.toLocaleString()} more characters` : ""}
    </pre>
  );
}
