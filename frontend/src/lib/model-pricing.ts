import type { CatalogModel, ModelCost } from "@/lib/models";

export const EMPTY_MODEL_COST: ModelCost = {
  input_per_m: 0,
  output_per_m: 0,
  pricing_unit: "per_million_tokens",
  unit_price: null,
  source: "catalog",
};

export function buildModelCostMap(models: Pick<CatalogModel, "id" | "cost">[]): Map<string, ModelCost> {
  return new Map(models.map((model) => [model.id, model.cost]));
}

export function getPricingSortValue(cost: ModelCost): number {
  if (cost.pricing_unit !== "per_million_tokens") {
    return cost.unit_price ?? 0;
  }
  return cost.input_per_m;
}

export function resolveModelCost(modelId: string, modelCosts: Map<string, ModelCost>): ModelCost {
  return modelCosts.get(modelId) ?? EMPTY_MODEL_COST;
}

export function estimateTokenCost(
  modelId: string,
  inputTokens: number,
  outputTokens: number,
  modelCosts: Map<string, ModelCost>,
): number {
  const cost = resolveModelCost(modelId, modelCosts);
  return (inputTokens * cost.input_per_m + outputTokens * cost.output_per_m) / 1_000_000;
}

function formatUsd(value: number): string {
  if (value === 0) return "$0";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  if (value < 1) return `$${value.toFixed(3)}`;
  return `$${value.toFixed(2)}`;
}

function pricingSourceLabel(source: ModelCost["source"]): string {
  return source === "enrichment" ? "Live source" : "Catalog source";
}

function unitLabel(pricingUnit: ModelCost["pricing_unit"]): string {
  switch (pricingUnit) {
    case "per_image":
      return "per image";
    case "per_second":
      return "per second";
    case "per_minute":
      return "per minute";
    case "per_million_characters":
      return "per 1M chars";
    default:
      return "input / output per 1M tokens";
  }
}

export function formatModelPricing(cost: ModelCost): { primary: string; secondary: string; source: string } {
  if (cost.pricing_unit !== "per_million_tokens") {
    return {
      primary: cost.unit_price && cost.unit_price > 0 ? formatUsd(cost.unit_price) : "Free",
      secondary: unitLabel(cost.pricing_unit),
      source: pricingSourceLabel(cost.source),
    };
  }

  if (cost.input_per_m === 0 && cost.output_per_m === 0) {
    return {
      primary: "Free",
      secondary: unitLabel(cost.pricing_unit),
      source: pricingSourceLabel(cost.source),
    };
  }

  return {
    primary: `${formatUsd(cost.input_per_m)} / ${formatUsd(cost.output_per_m)}`,
    secondary: unitLabel(cost.pricing_unit),
    source: pricingSourceLabel(cost.source),
  };
}
