export interface Agent {
  id: number
  slug: string
  name: string
  description: string | null
  system_prompt: string
  primary_model_id: string
  fallback_models: string[]
  temperature: number
  thinking_level: string | null
  verbosity_level: string | null
}

export type {
  AgentPreview,
  AgentPreviewMemoryDebug,
  AgentPreviewMemoryPlanEntry,
  AgentPreviewSection,
  PreviewProjectOption,
  PreviewScenario,
  PreviewTaskType,
} from './agent-preview'
