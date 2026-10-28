import { useQuery } from '@tanstack/react-query'
import { agentHubClient } from '@/lib/agent-hub-client'
import type { CatalogModel, ModelsResponse } from '@/lib/models'

export type { CatalogModel as ModelOption } from '@/lib/models'
export type ModelScores = CatalogModel['scores']

export const MODELS_CATALOG_QUERY_KEY = ['models', 'catalog'] as const

type CatalogResponse = ModelsResponse & {
  credential_only_providers?: Record<string, string>
}

async function fetchCatalog(): Promise<CatalogResponse> {
  return (await agentHubClient.models.catalog()) as unknown as CatalogResponse
}

/** The model catalog with its sync and health details, loaded once through the Agent Hub client. */
export function useModelsWithSync() {
  const query = useQuery({
    queryKey: MODELS_CATALOG_QUERY_KEY,
    queryFn: fetchCatalog,
    staleTime: Infinity,
    gcTime: Infinity,
  })
  return {
    models: query.data?.models ?? [],
    providers: query.data?.providers ?? {},
    credentialOnlyProviders: query.data?.credential_only_providers ?? {},
    lastSync: query.data?.last_sync ?? null,
    lastModelReview: query.data?.last_model_review ?? null,
    catalogHealth: query.data?.catalog_health ?? null,
    refetch: query.refetch,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
  }
}
