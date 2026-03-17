/// <reference path="../../types/web-speech.d.ts" />

import type { TranscriptionEngine, TranscriptionError } from './types'

// SSR-safe SpeechRecognition detection
export function getSpeechRecognitionCtor(): (new () => SpeechRecognition) | null {
    if (typeof window === 'undefined') return null;
    return (window.SpeechRecognition ?? window.webkitSpeechRecognition) ?? null;
}

export function resolveEngine(
    preferred: 'web-speech' | 'whisper' | undefined,
    hasWebSpeech: boolean,
    hasWhisperUrl: boolean,
): TranscriptionEngine {
    if (preferred === 'web-speech' && hasWebSpeech) return 'web-speech';
    if (preferred === 'whisper' && hasWhisperUrl) return 'whisper';
    if (preferred) {
        // Preferred not available, fall through to auto
    }
    if (hasWebSpeech) return 'web-speech';
    if (hasWhisperUrl) return 'whisper';
    return 'none';
}

/** Map Web Speech API error codes to our error type */
export function mapSpeechError(error: string): TranscriptionError {
    switch (error) {
        case 'not-allowed': return 'not-allowed';
        case 'no-speech': return 'no-speech';
        case 'network': return 'network';
        case 'aborted': return 'aborted';
        default: return 'not-supported';
    }
}
