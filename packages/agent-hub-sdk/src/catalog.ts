import type { Transport } from './http';
import type { Agent, AgentListResponse, ListAgentsParams, ModelInfo, ModelsResponse } from './types/catalog';

interface CallOptions {
    signal?: AbortSignal;
}

export interface ModelsApi {
    /** The model catalog. */
    list(options?: CallOptions): Promise<ModelInfo[]>;
    /** The catalog with its metadata (providers, last sync, health). */
    catalog(options?: CallOptions): Promise<ModelsResponse>;
}

export interface AgentsApi {
    /** Active agents by default; pass `active_only: false` for all. */
    list(params?: ListAgentsParams, options?: CallOptions): Promise<Agent[]>;
}

export function createModelsApi(transport: Transport): ModelsApi {
    const catalog = (options?: CallOptions) =>
        transport.json<ModelsResponse>('GET', '/api/models', { signal: options?.signal });
    return {
        catalog,
        async list(options) {
            return (await catalog(options)).models;
        },
    };
}

export function createAgentsApi(transport: Transport): AgentsApi {
    return {
        async list(params, options) {
            const page = await transport.json<AgentListResponse>('GET', '/api/agents', {
                query: params,
                signal: options?.signal,
            });
            return page.agents;
        },
    };
}
