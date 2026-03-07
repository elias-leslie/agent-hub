import type { TimelineEvent } from "@/types/events";

export interface SessionMemoryObservability {
  selectedCount: number;
  indexCount: number;
  selectedCitedCount: number;
  totalCitedCount: number;
  selectedCitationRate: number;
}

export function summarizeSessionMemoryObservability(
  events: TimelineEvent[]
): SessionMemoryObservability | null {
  let selectedCount = 0;
  let indexCount = 0;
  let selectedCitedCount = 0;
  let totalCitedCount = 0;
  let selectedRefs = new Set<string>();

  for (const event of events) {
    const toolInput = event.tool_input ?? {};

    if (event.event_type === "memory_inject") {
      selectedCount += Number(toolInput.reference_selected_count ?? 0);
      indexCount += Number(toolInput.reference_index_count ?? 0);
      selectedRefs = new Set(
        ((toolInput.reference_selected_uuids as unknown[]) ?? [])
          .filter(Boolean)
          .map((uuid) => String(uuid))
      );
      continue;
    }

    if (event.event_type === "memory_cite") {
      const citedUuids = (((toolInput.uuids as unknown[]) ?? []).filter(Boolean)).map(
        (uuid) => String(uuid)
      );
      totalCitedCount += citedUuids.length;
      selectedCitedCount += citedUuids.filter((uuid) => selectedRefs.has(uuid)).length;
    }
  }

  if (
    selectedCount === 0 &&
    indexCount === 0 &&
    selectedCitedCount === 0 &&
    totalCitedCount === 0
  ) {
    return null;
  }

  return {
    selectedCount,
    indexCount,
    selectedCitedCount,
    totalCitedCount,
    selectedCitationRate:
      selectedCount > 0 ? Math.round((selectedCitedCount / selectedCount) * 100) : 0,
  };
}
