export type CompactnessKind = "prompt" | "memory";

export interface CompactnessReport {
  kind: CompactnessKind;
  chars: number;
  lines: number;
  tokens: number;
  warnings: string[];
}

const FILLER_PATTERNS: Array<[string, RegExp]> = [
  ["just", /\bjust\b/i],
  ["really", /\breally\b/i],
  ["basically", /\bbasically\b/i],
  ["please", /\bplease\b/i],
  ["let me know", /\blet me know\b/i],
  ["feel free", /\bfeel free\b/i],
  ["i recommend", /\bi recommend\b/i],
  ["i suggest", /\bi suggest\b/i],
  ["you should", /\byou should\b/i],
  ["make sure", /\bmake sure\b/i],
];
const EXAMPLE_PATTERN = /\bfor example\b|\be\.g\.\b|example:/gi;

function lineCount(content: string): number {
  return content ? content.split("\n").length : 0;
}

function estimateTokens(content: string): number {
  return content ? Math.ceil(content.length / 4) : 0;
}

function detectFillers(content: string): string[] {
  return FILLER_PATTERNS
    .filter(([, pattern]) => pattern.test(content))
    .map(([label]) => label);
}

export function analyzeCompactness(
  content: string,
  kind: CompactnessKind
): CompactnessReport {
  const chars = content.length;
  const lines = lineCount(content);
  const tokens = estimateTokens(content);
  const warnings: string[] = [];
  const fillerHits = detectFillers(content);

  if (kind === "prompt") {
    if (tokens > 350) {
      warnings.push(`large prompt (${tokens} tok). Hot-path prompts pay this every turn.`);
    }
    if (lines > 80) {
      warnings.push(`long prompt (${lines} lines). Collapse repeated examples and overlap.`);
    }
  } else {
    if (chars > 280) {
      warnings.push(`long memory (${chars} chars). Keep one atomic rule; split if needed.`);
    }
    if (lines > 4) {
      warnings.push(`multi-line memory (${lines} lines). Prefer one short rule body.`);
    }
  }

  if (fillerHits.length > 0) {
    warnings.push(`filler terms found: ${fillerHits.slice(0, 4).join(", ")}`);
  }

  const exampleHits = content.match(EXAMPLE_PATTERN)?.length ?? 0;
  if (exampleHits > 1) {
    warnings.push("repeated example markers found. Keep only examples that earn tokens.");
  }

  return { kind, chars, lines, tokens, warnings };
}
