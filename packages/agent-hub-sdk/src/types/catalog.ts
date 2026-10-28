/** Models and agents, written by hand from `ModelInfo` / `AgentResponse` in the backend OpenAPI. */

export interface ModelCapabilities {
    can_generate_images: boolean;
    has_vision: boolean;
    can_edit_images: boolean;
    has_thinking?: boolean;
    supports_pdf?: boolean;
    supports_audio?: boolean;
    supports_tool_execution?: boolean;
    supports_verbosity?: boolean;
    supports_xhigh?: boolean;
    supports_session_cache?: boolean;
    supports_chat?: boolean;
    supports_typed_judgment?: boolean;
    max_state_question_tokens?: number | null;
    max_output_tokens?: number;
    thinking_level_map?: Record<string, unknown> | null;
}

export interface ModelCost {
    input_per_m: number;
    output_per_m: number;
    pricing_unit?: string;
    unit_price?: number | null;
    cache_read_per_million?: number | null;
    cache_write_per_million?: number | null;
    service_tiers?: Record<string, number>;
    source?: string;
}

export interface ModelScores {
    coding: number;
    reasoning: number;
    planning: number;
    tool_use: number;
    instruction: number;
    design: number;
    composite: number;
}

export interface ModelInfo {
    id: string;
    name: string;
    alias: string;
    hint: string;
    provider: string;
    upstream_id?: string | null;
    access_programs?: Record<string, unknown> | null;
    routable: boolean;
    scores: ModelScores;
    cost: ModelCost;
    context_window: number;
    speed_tier: string;
    capabilities: ModelCapabilities;
    release_date?: string | null;
    knowledge_cutoff?: string | null;
    family?: string | null;
    availability?: string | null;
    enrichment?: Record<string, unknown> | null;
}

export interface ModelsResponse {
    models: ModelInfo[];
    providers?: Record<string, string>;
    credential_only_providers?: Record<string, string>;
    last_sync?: string | null;
    last_model_review?: string | null;
    catalog_health?: Record<string, unknown> | null;
}

export interface Agent {
    id: number;
    slug: string;
    name: string;
    description: string | null;
    system_prompt: string;
    primary_model_id: string;
    fallback_models: string[];
    escalation_model_id: string | null;
    strategies: Record<string, unknown>;
    temperature: number;
    thinking_level: string | null;
    verbosity_level: string | null;
    is_active: boolean;
    is_coding_agent: boolean;
    memory_config: Record<string, unknown> | null;
    effective_memory_config: Record<string, unknown>;
    max_concurrency: number | null;
    max_subagent_concurrency: number | null;
    daily_token_budget: number | null;
    hourly_request_limit: number | null;
    version: number;
    created_at: string;
    updated_at: string;
}

export interface AgentListResponse {
    agents: Agent[];
    total: number;
}

export interface ListAgentsParams {
    /** Default true. */
    active_only?: boolean;
    is_coding_agent?: boolean;
    limit?: number;
    offset?: number;
}
