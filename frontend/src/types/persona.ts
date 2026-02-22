export interface Persona {
  id: number;
  name: string;
  personality: string | null;
  heartbeat_instructions: string | null;
  user_context: string | null;
  tools_guidance: string | null;
  voice_id: string;
  voice_enabled: boolean;
  heartbeat_interval_minutes: number;
  avatar_url: string | null;
  greeting: string | null;
  onboarding_complete: boolean;
  agent_slug: string;
  version: number;
  updated_at: string | null;
}

export interface PersonaUpdate {
  name?: string;
  personality?: string;
  heartbeat_instructions?: string;
  user_context?: string;
  tools_guidance?: string;
  voice_id?: string;
  voice_enabled?: boolean;
  heartbeat_interval_minutes?: number;
  avatar_url?: string;
  greeting?: string;
}
