import { useRef, useCallback } from 'react';
import type { TranscriptionStatus, TranscriptionError } from './types'
import { getSpeechRecognitionCtor, mapSpeechError } from './utils'

export interface WebSpeechEngineHandlers {
    setStatus: (status: TranscriptionStatus | ((prev: TranscriptionStatus) => TranscriptionStatus)) => void
    setError: (error: TranscriptionError) => void
    setInterimTranscript: (text: string) => void
    setFinalTranscript: (text: string) => void
}

export interface WebSpeechEngineReturn {
    startWebSpeech: () => void
    stopWebSpeech: () => void
    cleanup: () => void
}

export function useWebSpeechEngine(
    lang: string | undefined,
    handlers: WebSpeechEngineHandlers
): WebSpeechEngineReturn {
    const { setStatus, setError, setInterimTranscript, setFinalTranscript } = handlers;

    const recognitionRef = useRef<SpeechRecognition | null>(null);
    const isListeningRef = useRef(false);
    const startWebSpeechRef = useRef<() => void>(null);
    const accumulatedTextRef = useRef('');

    const SpeechRecognition = getSpeechRecognitionCtor();

    const startWebSpeech = useCallback(() => {
        if (!SpeechRecognition) return;

        // Detach handlers from old instance BEFORE abort to prevent
        // cascading onend events from creating parallel instances.
        if (recognitionRef.current) {
            recognitionRef.current.onresult = null;
            recognitionRef.current.onerror = null;
            recognitionRef.current.onend = null;
            recognitionRef.current.abort();
            recognitionRef.current = null;
        }

        const recognition = new SpeechRecognition();
        // Use continuous=false — each instance captures exactly one phrase.
        // Auto-restart in onend gives continuous-like behavior without the
        // mobile Chrome bug where continuous=true re-delivers finalized results.
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = lang ?? (typeof navigator !== 'undefined' ? navigator.language : 'en-US');

        // Guard: only process the final result once per instance
        let finalProcessed = false;

        recognition.onresult = (event: SpeechRecognitionEvent) => {
            const result = event.results[0];
            if (!result) return;

            if (result.isFinal && !finalProcessed) {
                finalProcessed = true;
                const text = result[0].transcript.trim();
                if (text) {
                    accumulatedTextRef.current = accumulatedTextRef.current
                        ? `${accumulatedTextRef.current} ${text}`
                        : text;
                }
                setFinalTranscript(accumulatedTextRef.current);
                setInterimTranscript('');
            } else if (!result.isFinal) {
                setInterimTranscript(result[0].transcript);
            }
        };

        recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
            // no-speech is expected between phrases on mobile — just restart
            if (event.error === 'no-speech' && isListeningRef.current) {
                return;
            }
            setError(mapSpeechError(event.error));
            setStatus('error');
        };

        recognition.onend = () => {
            if (isListeningRef.current) {
                // Auto-restart: create a fresh instance for the next phrase
                try {
                    startWebSpeechRef.current?.();
                } catch {
                    setStatus((prev) => prev === 'error' ? prev : 'idle');
                    recognitionRef.current = null;
                    isListeningRef.current = false;
                }
            } else {
                setStatus((prev) => prev === 'error' ? prev : 'idle');
                recognitionRef.current = null;
            }
        };

        recognitionRef.current = recognition;
        isListeningRef.current = true;
        setError(null);
        setStatus('listening');
        recognition.start();
    }, [SpeechRecognition, lang, setStatus, setError, setInterimTranscript, setFinalTranscript]);

    // Keep ref in sync for self-referencing auto-restart
    startWebSpeechRef.current = startWebSpeech;

    const stopWebSpeech = useCallback(() => {
        isListeningRef.current = false;
        recognitionRef.current?.stop();
    }, []);

    const cleanup = useCallback(() => {
        isListeningRef.current = false;
        recognitionRef.current?.abort();
    }, []);

    return { startWebSpeech, stopWebSpeech, cleanup };
}
