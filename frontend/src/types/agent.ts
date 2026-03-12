export interface Agent {
    id: number;
    slug: string;
    name: string;
    description: string | null;
    system_prompt: string;
    primary_model_id: string;
    fallback_models: string[];
    temperature: number;
    thinking_level: string | null;
    verbosity_level: string | null;
}

export interface AgentPreview {
    slug: string;
    name: string;
    combined_prompt: string;
    full_context: string;
    memory_query: string;
    loaded_memory_uuids: string[];
    reference_uuids: string[];
    mandate_count: number;
    guardrail_count?: number;
    mandate_uuids: string[];
    guardrail_uuids?: string[];
    task_type?: "chat" | "heartbeat" | "wake" | "review" | null;
    phase?: string | null;
    project_id?: string | null;
    task_prompt?: string | null;
    sections?: Array<{
        label: string;
        source_kind: string;
        source_id: string;
        placement: string;
        content_hash: string;
        chars: number;
        estimated_tokens: number;
        content: string;
        role?: string | null;
        priority?: number | null;
        updated_at?: string | null;
    }>;
}
