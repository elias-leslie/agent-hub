import { describe, expect, it } from "vitest";

import { analyzeCompactness } from "@/lib/compactness";

describe("analyzeCompactness", () => {
  it("flags large filler-heavy prompts", () => {
    const report = analyzeCompactness(
      `Please keep this prompt really clear.\n${"Example: keep signal.\n".repeat(90)}`,
      "prompt"
    );

    expect(report.tokens).toBeGreaterThan(350);
    expect(report.warnings.some((warning) => warning.includes("large prompt"))).toBe(true);
    expect(report.warnings.some((warning) => warning.includes("long prompt"))).toBe(true);
    expect(report.warnings.some((warning) => warning.includes("filler terms found"))).toBe(true);
    expect(report.warnings.some((warning) => warning.includes("repeated example markers"))).toBe(true);
  });

  it("flags long multi-line memories", () => {
    const report = analyzeCompactness(
      [
        "**Prompt Hygiene**: Keep prompts compact and focused.",
        "Use one canonical prompt.",
        "Drop overlap.",
        "Drop filler.",
        "Split extra rules.",
      ].join("\n"),
      "memory"
    );

    expect(report.warnings.some((warning) => warning.includes("multi-line memory"))).toBe(true);
  });

  it("leaves lean content warning-free", () => {
    expect(
      analyzeCompactness("**Quality Checks**: Use dt for repo checks.", "memory").warnings
    ).toEqual([]);
  });
});
