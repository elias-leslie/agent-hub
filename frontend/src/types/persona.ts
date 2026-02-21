export interface Persona {
  id: number;
  name: string;
  soul: string | null;
  voice_id: string;
  voice_enabled: boolean;
  heartbeat_interval_minutes: number;
  avatar_url: string | null;
  greeting: string | null;
  agent_slug: string;
  version: number;
  updated_at: string | null;
}

export interface PersonaUpdate {
  name?: string;
  soul?: string;
  voice_id?: string;
  voice_enabled?: boolean;
  heartbeat_interval_minutes?: number;
  avatar_url?: string;
  greeting?: string;
}
