import { GitBranch } from "lucide-react";
import { OK, WORK, BAD } from "./colors";
import { hasStatusFields, statusLineFields, type StatusLineInput } from "./status-line";

/**
 * The dim mono line under the composer: the model asked for and the one answering, the session's tokens and
 * cost, how full the context is, the git branch. A field the data does not have is left out.
 */
export function StatusLine(props: StatusLineInput) {
  const fields = statusLineFields(props);
  if (!hasStatusFields(fields)) return null;
  const used = fields.contextPercent;
  return (
    <div
      data-testid="status-line"
      className="mt-1.5 flex flex-wrap items-center gap-x-3.5 gap-y-0.5 font-mono text-xs text-muted-foreground/80"
    >
      {fields.requested || fields.served ? (
        <span data-testid="status-model" className="min-w-0 truncate">
          {fields.requested ? (
            <>
              requested <span className="text-muted-foreground">{fields.requested}</span>
            </>
          ) : null}
          {fields.requested && fields.served ? " → " : null}
          {fields.served ? (
            <>
              {fields.answerLabel} <span className="text-muted-foreground">{fields.served}</span>
            </>
          ) : null}
        </span>
      ) : null}
      {fields.inputTokens ? (
        <span data-testid="status-in">
          in <span className="text-muted-foreground">{fields.inputTokens}</span>
        </span>
      ) : null}
      {fields.outputTokens ? (
        <span data-testid="status-out">
          out <span className="text-muted-foreground">{fields.outputTokens}</span>
        </span>
      ) : null}
      {fields.cost ? (
        <span data-testid="status-cost" className="text-muted-foreground">
          {fields.cost}
        </span>
      ) : null}
      {used !== undefined ? (
        <span data-testid="status-context" className="inline-flex items-center gap-1.5">
          context
          <span
            role="meter"
            aria-label="Context used"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={used}
            className="inline-block h-[5px] w-[60px] overflow-hidden rounded-[3px] bg-border"
          >
            <span
              className="block h-full"
              style={{ width: `${fields.contextUnderOne ? 1 : used}%`, backgroundColor: used >= 90 ? BAD : used >= 70 ? WORK : OK }}
            />
          </span>
          <span className="text-muted-foreground">{fields.contextUnderOne ? "<1" : used}%</span>
        </span>
      ) : null}
      {fields.branch ? (
        <span data-testid="status-branch" className="inline-flex items-center gap-1 text-muted-foreground">
          <GitBranch aria-hidden className="h-3 w-3" />
          {fields.branch}
        </span>
      ) : null}
    </div>
  );
}
