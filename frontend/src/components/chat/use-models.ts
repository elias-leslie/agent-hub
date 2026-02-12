import { useQuery } from "@tanstack/react-query";
import { fetchApi } from "@/lib/api-config";

export interface ModelOption {
  id: string;
  alias: string;
  name: string;
  hint: string;
  provider: "claude" | "gemini" | "openrouter" | "openai" | "xai" | "zhipu";
}

async function fetchModels(): Promise<ModelOption[]> {
  const response = await fetchApi("/api/models");
  if (!response.ok) {
    throw new Error(`Failed to fetch models: ${response.status}`);
  }
  const data = await response.json();
  return data.models;
}

export function useModels(): ModelOption[] {
  const { data } = useQuery({
    queryKey: ["models"],
    queryFn: fetchModels,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return data ?? [];
}
