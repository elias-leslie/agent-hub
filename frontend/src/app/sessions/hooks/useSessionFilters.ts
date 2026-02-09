import { useState, useMemo } from "react";
import { type SessionListItem } from "@/lib/api";
import { estimateCost } from "../utils";
import { type SortField, type SortDirection } from "../types";

interface UseSessionFiltersProps {
  sessions: SessionListItem[];
  sortField: SortField;
  sortDirection: SortDirection;
}

export function useSessionFilters({ sessions, sortField, sortDirection }: UseSessionFiltersProps) {
  const [modelFilter, setModelFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");

  const filteredAndSorted = useMemo(() => {
    let filtered = sessions;

    // Filter by model
    if (modelFilter) {
      filtered = filtered.filter((s) => s.model === modelFilter);
    }

    // Filter by search
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (s) =>
          s.id.toLowerCase().includes(query) ||
          s.project_id.toLowerCase().includes(query) ||
          s.model.toLowerCase().includes(query) ||
          s.agent_slug?.toLowerCase().includes(query)
      );
    }

    // Sort
    const sorted = [...filtered].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "project":
          cmp = a.project_id.localeCompare(b.project_id);
          break;
        case "model":
          cmp = a.model.localeCompare(b.model);
          break;
        case "status":
          cmp = a.status.localeCompare(b.status);
          break;
        case "tokens":
          cmp = (a.total_input_tokens + a.total_output_tokens) - (b.total_input_tokens + b.total_output_tokens);
          break;
        case "cost": {
          const costA = estimateCost(a.model, a.total_input_tokens, a.total_output_tokens);
          const costB = estimateCost(b.model, b.total_input_tokens, b.total_output_tokens);
          cmp = costA - costB;
          break;
        }
        case "time":
          cmp = new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime();
          break;
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });

    return sorted;
  }, [sessions, modelFilter, searchQuery, sortField, sortDirection]);

  const pageStats = useMemo(() => {
    if (!filteredAndSorted.length) return null;
    const totalTokens = filteredAndSorted.reduce(
      (sum, s) => sum + s.total_input_tokens + s.total_output_tokens,
      0
    );
    const totalCost = filteredAndSorted.reduce(
      (sum, s) => sum + estimateCost(s.model, s.total_input_tokens, s.total_output_tokens),
      0
    );
    return { totalTokens, totalCost };
  }, [filteredAndSorted]);

  return {
    modelFilter,
    setModelFilter,
    searchQuery,
    setSearchQuery,
    filteredAndSorted,
    pageStats,
  };
}
