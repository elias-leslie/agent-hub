import type { ModelOption } from "@/components/chat/use-models";
import type { ComplexityTier, QualityPreference } from "./tier-matrix-grid";

const MIN_COMPOSITE: Record<ComplexityTier, number> = {
  1: 40,
  2: 60,
  3: 72,
  4: 79,
};

export function selectModelForCell(
  models: ModelOption[],
  provider: string,
  complexity: ComplexityTier,
  preference: QualityPreference
): ModelOption | null {
  const providerModels = models.filter((m) => m.provider === provider);
  const threshold = MIN_COMPOSITE[complexity];
  let candidates = providerModels.filter(
    (m) => m.scores.composite >= threshold
  );

  // Relax threshold if no candidates
  if (candidates.length === 0) {
    candidates = providerModels.filter(
      (m) => m.scores.composite >= threshold - 10
    );
  }
  if (candidates.length === 0) {
    candidates = providerModels;
  }
  if (candidates.length === 0) return null;

  switch (preference) {
    case "economy":
      return candidates.sort(
        (a, b) =>
          a.cost.input_per_m +
          a.cost.output_per_m -
          (b.cost.input_per_m + b.cost.output_per_m)
      )[0];
    case "standard": {
      return candidates.sort((a, b) => {
        const costA = a.cost.input_per_m + a.cost.output_per_m || 0.01;
        const costB = b.cost.input_per_m + b.cost.output_per_m || 0.01;
        return b.scores.composite / costB - a.scores.composite / costA;
      })[0];
    }
    case "advanced":
      return candidates.sort(
        (a, b) => b.scores.composite - a.scores.composite
      )[0];
  }
}
