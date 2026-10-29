/**
 * What the status line under the composer says. Each field is present only when the data has it: unknown is
 * absent, never 0.
 */

import type { ChatMessage } from "../../types/chat";
import { compactCount, formatUsd } from "./tool-format";

export interface StatusLineInput {
  /** The model asked for and the one answering, from the latest answer. */
  requestedModel?: string | null;
  servedModel?: string | null;
  /** A turn is running: the answering model is "answering", else "answered". */
  busy?: boolean;
  inputTokens?: number | null;
  outputTokens?: number | null;
  costUsd?: number | null;
  /** 0-100. */
  contextPercent?: number | null;
  branch?: string | null;
}

export interface StatusLineFields {
  requested?: string;
  /** Label before the served model: "answering" while a turn runs, "answered" after. */
  answerLabel?: "answering" | "answered";
  served?: string;
  inputTokens?: string;
  outputTokens?: string;
  cost?: string;
  /** Whole percent, 0-100. */
  contextPercent?: number;
  /** The context is used, but by less than one percent: shown as "<1%" rather than 0. */
  contextUnderOne?: boolean;
  branch?: string;
}

function known(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function statusLineFields(input: StatusLineInput): StatusLineFields {
  const out: StatusLineFields = {};
  if (input.requestedModel) out.requested = input.requestedModel;
  if (input.servedModel) {
    out.served = input.servedModel;
    out.answerLabel = input.busy ? "answering" : "answered";
  }
  if (known(input.inputTokens) && input.inputTokens > 0) out.inputTokens = compactCount(input.inputTokens);
  if (known(input.outputTokens) && input.outputTokens > 0) out.outputTokens = compactCount(input.outputTokens);
  if (known(input.costUsd) && input.costUsd > 0) out.cost = formatUsd(input.costUsd);
  if (known(input.contextPercent)) {
    const clamped = Math.min(100, Math.max(0, input.contextPercent));
    out.contextPercent = Math.round(clamped);
    if (clamped > 0 && out.contextPercent === 0) out.contextUnderOne = true;
  }
  if (input.branch) out.branch = input.branch;
  return out;
}

export function hasStatusFields(fields: StatusLineFields): boolean {
  return Object.keys(fields).some((key) => key !== "answerLabel");
}

/**
 * The session's cost, when every answer in view reported one. A reopened session has answers that did not, and a
 * partial sum would understate the session, so it is left out then.
 */
export function sessionCost(messages: ChatMessage[]): number | undefined {
  const answers = messages.filter((message) => message.role === "assistant");
  if (answers.length === 0) return undefined;
  let total = 0;
  for (const answer of answers) {
    if (typeof answer.costUsd !== "number") return undefined;
    total += answer.costUsd;
  }
  return total;
}
