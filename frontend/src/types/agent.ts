export interface Agent {
    id: number;
    slug: string;
    name: string;
    description: string | null;
    system_prompt: string;
    primary_model_id: string;
    fallback_models: string[];
    temperature: number;
}

export interface AgentPreview {
    slug: string;
    name: string;
    combined_prompt: string;
    mandate_count: number;
    mandate_uuids: string[];
}
