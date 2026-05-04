export interface PersonaUserProfile {
  user_identity?: string | null
  work_context?: string | null
  communication_style?: string | null
  autonomy_level?: string | null
  notification_preferences?: string | null
  timezone?: string | null
  working_schedule?: string | null
  priorities_values?: string | null
  tools_and_integrations?: string | null
  boundaries_and_escalation?: string | null
}

export interface PersonaLimits {
  max_turns?: number | null
  [key: string]: number | null | undefined
}

export interface Persona {
  id: number
  name: string
  personality: string | null
  user_profile: PersonaUserProfile | null
  heartbeat_instructions: string | null
  user_context: string | null
  voice_id: string
  voice_enabled: boolean
  heartbeat_interval_minutes: number
  execution_state: 'active' | 'paused'
  avatar_url: string | null
  greeting: string | null
  onboarding_complete: boolean
  onboarding_phase:
    | 'not_started'
    | 'in_progress'
    | 'pending_approval'
    | 'complete'
  onboarding_attempts: number
  session_reset_mode: 'off' | 'daily' | 'idle'
  session_reset_hour: number
  session_reset_idle_minutes: number
  limits: PersonaLimits | null
  agent_slug: string
  version: number
  updated_at: string | null
}

export interface PersonaUpdate {
  name?: string
  personality?: string
  user_profile?: PersonaUserProfile | null
  heartbeat_instructions?: string
  user_context?: string
  voice_id?: string
  voice_enabled?: boolean
  heartbeat_interval_minutes?: number
  execution_state?: 'active' | 'paused'
  avatar_url?: string
  greeting?: string
  session_reset_mode?: 'off' | 'daily' | 'idle'
  session_reset_hour?: number
  session_reset_idle_minutes?: number
  limits?: PersonaLimits | null
}
