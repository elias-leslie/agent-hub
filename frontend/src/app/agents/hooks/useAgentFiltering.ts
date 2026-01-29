import { useMemo } from "react";
import type { Agent, AgentMetrics, SortField, SortDirection } from "../lib/types";

export function useAgentFiltering({
  agents,
  searchQuery,
  sortField,
  sortDirection,
  metricsData,
}: {
  agents: Agent[] | undefined;
  searchQuery: string;
  sortField: SortField;
  sortDirection: SortDirection;
  metricsData: Record<string, AgentMetrics> | undefined;
}) {
  return useMemo(() => {
    if (!agents) return [];

    let filtered = agents;

    // Filter by search
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (a) =>
          a.slug.toLowerCase().includes(query) ||
          a.name.toLowerCase().includes(query) ||
          a.description?.toLowerCase().includes(query)
      );
    }

    // Sort
    return [...filtered].sort((a, b) => {
      let cmp = 0;
      const metricsA = metricsData?.[a.slug];
      const metricsB = metricsData?.[b.slug];

      switch (sortField) {
        case "name":
          cmp = a.name.localeCompare(b.name);
          break;
        case "model":
          cmp = a.primary_model_id.localeCompare(b.primary_model_id);
          break;
        case "status":
          cmp = (a.is_active ? 1 : 0) - (b.is_active ? 1 : 0);
          break;
        case "requests":
          cmp = (metricsA?.requests_24h ?? 0) - (metricsB?.requests_24h ?? 0);
          break;
        case "latency":
          cmp = (metricsA?.avg_latency_ms ?? 0) - (metricsB?.avg_latency_ms ?? 0);
          break;
        case "success":
          cmp = (metricsA?.success_rate ?? 100) - (metricsB?.success_rate ?? 100);
          break;
        case "version":
          cmp = a.version - b.version;
          break;
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });
  }, [agents, searchQuery, sortField, sortDirection, metricsData]);
}
