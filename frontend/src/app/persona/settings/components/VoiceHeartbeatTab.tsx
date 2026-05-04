import { useVoicePreferences, type VoiceOption } from '@agent-hub/chat-ui'
import { Check, Play, Search } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { useHeartbeat } from '@/app/persona/hooks/useHeartbeat'
import type { PersonaAutosaveState } from '@/app/persona/hooks/usePersona'
import { buildApiUrl, fetchApi, getApiBaseUrl } from '@/lib/api-config'
import { cn } from '@/lib/utils'
import type { Persona, PersonaUpdate } from '@/types/persona'

interface VoiceHeartbeatTabProps {
  persona: Persona
  onUpdate: (fields: PersonaUpdate) => void
  autosave: PersonaAutosaveState
}

export function VoiceHeartbeatTab({
  persona,
  onUpdate,
  autosave,
}: VoiceHeartbeatTabProps) {
  const [search, setSearch] = useState('')
  const { status: heartbeatStatus } = useHeartbeat()

  const {
    voices,
    selectedVoice,
    ttsEnabled,
    setSelectedVoice,
    setTtsEnabled,
    previewVoice,
  } = useVoicePreferences({
    ttsBaseUrl:
      getApiBaseUrl() ||
      (typeof window !== 'undefined' ? window.location.origin : ''),
    preferencesEndpoint: buildApiUrl('/api/persona'),
    fetchFn: (url: string, options?: RequestInit) => fetchApi(url, options),
  })

  const filteredVoices = useMemo(() => {
    const lowerSearch = search.toLowerCase()
    return voices.filter(
      (v) =>
        v.name.toLowerCase().includes(lowerSearch) ||
        v.locale.toLowerCase().includes(lowerSearch) ||
        v.personalities.some((p) => p.toLowerCase().includes(lowerSearch)),
    )
  }, [voices, search])

  const grouped = useMemo(() => {
    const groups: Record<string, VoiceOption[]> = {}
    for (const v of filteredVoices) {
      const key = v.gender || 'Other'
      if (!groups[key]) groups[key] = []
      groups[key].push(v)
    }
    return groups
  }, [filteredVoices])

  const handleHeartbeatChange = useCallback(
    (minutes: number) => {
      onUpdate({ heartbeat_interval_minutes: minutes })
    },
    [onUpdate],
  )
  const runtime = heartbeatStatus?.runtime
  const heartbeatWarning = runtime?.warnings?.[0] ?? null
  const heartbeatDisabled = persona.heartbeat_interval_minutes === 0

  return (
    <div className="space-y-8">
      <div>
        <p className="section-kicker">Voice & Heartbeat</p>
        <h2 className="section-heading mt-2">Realtime Presence</h2>
        <p className="section-copy mt-2 max-w-3xl">
          Configure speech output, review heartbeat readiness, and tune how
          often this persona checks in autonomously.
        </p>
      </div>

      <div className="space-y-4 section-card">
        <div className="section-header gap-4">
          <div>
            <h2 className="section-heading">Voice</h2>
            <p className="section-copy mt-2">
              Text-to-speech voice selection for persona responses.
            </p>
          </div>
          <div className="page-pill">Autosave {autosave.status}</div>
        </div>

        {/* TTS Toggle */}
        <div className="detail-card max-w-md flex items-center justify-between">
          <span className="text-sm text-slate-300">Text-to-speech</span>
          <button
            onClick={() => setTtsEnabled(!ttsEnabled)}
            aria-label={
              ttsEnabled ? 'Disable text-to-speech' : 'Enable text-to-speech'
            }
            className={cn(
              'relative w-10 h-5 rounded-full transition-colors duration-200',
              ttsEnabled ? 'bg-amber-500' : 'bg-slate-600',
            )}
          >
            <span
              className={cn(
                'absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-slate-200 shadow transition-transform duration-200',
                ttsEnabled && 'translate-x-5',
              )}
            />
          </button>
        </div>

        {/* Voice Search */}
        <div className="relative max-w-md">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search voices..."
            className="control-input pl-8"
          />
        </div>

        {/* Voice List */}
        <div className="max-h-[280px] max-w-md overflow-y-auto rounded-2xl border border-slate-800/80 bg-slate-950/65">
          {Object.entries(grouped).map(([gender, groupVoices]) => (
            <div key={gender}>
              <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400 bg-slate-800/50 sticky top-0">
                {gender}
              </div>
              {groupVoices.map((voice) => (
                <button
                  key={voice.id}
                  onClick={() => setSelectedVoice(voice.id)}
                  aria-label={`Select voice ${voice.name}`}
                  className={cn(
                    'w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-800/50 transition-colors',
                    voice.id === selectedVoice && 'bg-amber-900/20',
                  )}
                >
                  <div
                    role="button"
                    aria-label={`Preview voice ${voice.name}`}
                    tabIndex={0}
                    onClick={(e) => {
                      e.stopPropagation()
                      previewVoice(voice.id)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.stopPropagation()
                        e.preventDefault()
                        previewVoice(voice.id)
                      }
                    }}
                    className="flex-shrink-0 p-0.5 rounded text-slate-400 hover:text-slate-300"
                  >
                    <Play className="w-3 h-3" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="text-xs font-medium text-slate-100 truncate block">
                      {voice.name}
                    </span>
                    {voice.personalities.length > 0 && (
                      <span className="text-[10px] text-slate-400">
                        {voice.personalities.slice(0, 2).join(', ')}
                      </span>
                    )}
                  </div>
                  {voice.id === selectedVoice && (
                    <Check className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
                  )}
                </button>
              ))}
            </div>
          ))}
          {filteredVoices.length === 0 && (
            <div className="px-3 py-4 text-center text-xs text-slate-400">
              No voices found
            </div>
          )}
        </div>
      </div>

      {/* Heartbeat Section */}
      <div className="space-y-4 section-card">
        <div>
          <h2 className="section-heading">Heartbeat</h2>
          <p className="section-copy mt-2">
            Autonomous check-in schedule and runtime readiness.
          </p>
        </div>

        <div className="detail-card max-w-md flex items-center justify-between">
          <span className="text-sm text-slate-300">Check-in interval</span>
          <select
            aria-label="Heartbeat interval"
            value={persona.heartbeat_interval_minutes}
            onChange={(e) => handleHeartbeatChange(Number(e.target.value))}
            className="control-select cursor-pointer"
          >
            <option value={15}>15 min</option>
            <option value={30}>30 min</option>
            <option value={60}>1 hour</option>
            <option value={120}>2 hours</option>
            <option value={240}>4 hours</option>
            <option value={0}>Off</option>
          </select>
        </div>
        <p className="text-[10px] text-slate-400 max-w-md">
          How often {persona.name} runs autonomous system checks
        </p>

        <div className="section-card max-w-md space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
                Heartbeat Runtime
              </p>
              <p className="mt-1 text-sm font-medium text-slate-100">
                {runtime?.model_display_name || runtime?.model || 'Unavailable'}
              </p>
              <p className="text-xs text-slate-400">
                {runtime
                  ? `${runtime.provider} · thinking ${runtime.thinking_level || 'off'}`
                  : 'Runtime status unavailable'}
              </p>
            </div>
            <span
              className={cn(
                'inline-flex items-center rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide',
                heartbeatDisabled
                  ? 'bg-slate-800 text-slate-300'
                  : runtime?.heartbeat_supported
                    ? 'bg-emerald-900/30 text-emerald-400'
                    : 'bg-rose-900/30 text-rose-400',
              )}
            >
              {heartbeatDisabled
                ? 'Disabled'
                : runtime?.heartbeat_supported
                  ? 'Ready'
                  : 'Attention'}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2 text-xs text-slate-300">
            <div className="detail-card px-3 py-2">
              Tools: {runtime?.supports_tools ? 'supported' : 'not supported'}
            </div>
            <div className="detail-card px-3 py-2">
              Session cache:{' '}
              {runtime?.supports_session_cache ? 'supported' : 'not supported'}
            </div>
          </div>

          {heartbeatDisabled && (
            <div className="rounded-lg border border-amber-800 bg-amber-950/40 px-3 py-2 text-xs text-amber-200">
              Heartbeat is currently off, so {persona.name} is not autonomously
              driving work.
            </div>
          )}

          {heartbeatWarning && (
            <div className="rounded-lg border border-rose-800 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">
              {heartbeatWarning}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
