export type TranscriptionEngine = 'web-speech' | 'whisper' | 'none'
export type TranscriptionStatus = 'idle' | 'listening' | 'processing' | 'error'
export type TranscriptionError =
    | 'not-supported' | 'not-allowed' | 'no-speech'
    | 'network' | 'aborted' | 'whisper-unavailable' | null

export interface UseTranscriptionOptions {
    /** Agent Hub voice WebSocket URL for whisper fallback. If not provided, whisper engine unavailable. */
    whisperWsUrl?: string
    /** Force a specific engine instead of auto-detecting */
    preferredEngine?: 'web-speech' | 'whisper'
    /** Language for Web Speech API (default: navigator.language || 'en-US') */
    lang?: string
}

export interface UseTranscriptionReturn {
    engine: TranscriptionEngine
    isSupported: boolean
    status: TranscriptionStatus
    error: TranscriptionError
    interimTranscript: string
    finalTranscript: string
    startListening: () => void
    stopListening: () => void
    resetTranscript: () => void
}
