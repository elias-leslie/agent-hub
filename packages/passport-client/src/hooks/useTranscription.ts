"use client";

import { useState, useCallback, useEffect, useRef } from 'react';
import type {
    TranscriptionEngine,
    TranscriptionStatus,
    TranscriptionError,
    UseTranscriptionOptions,
    UseTranscriptionReturn,
} from './transcription/types'
import { getSpeechRecognitionCtor, resolveEngine } from './transcription/utils'
import { useWebSpeechEngine } from './transcription/webSpeechEngine'
import { useWhisperEngine } from './transcription/whisperEngine'

// Re-export types for backward compatibility
export type {
    TranscriptionEngine,
    TranscriptionStatus,
    TranscriptionError,
    UseTranscriptionOptions,
    UseTranscriptionReturn,
}

export function useTranscription(options: UseTranscriptionOptions = {}): UseTranscriptionReturn {
    const { whisperWsUrl, preferredEngine, lang } = options;

    const SpeechRecognition = getSpeechRecognitionCtor();
    const hasWebSpeech = SpeechRecognition !== null;
    const hasWhisperUrl = Boolean(whisperWsUrl);

    const engine = resolveEngine(preferredEngine, hasWebSpeech, hasWhisperUrl);
    const isSupported = engine !== 'none';

    const [status, setStatus] = useState<TranscriptionStatus>('idle');
    const [error, setError] = useState<TranscriptionError>(null);
    const [interimTranscript, setInterimTranscript] = useState('');
    const [finalTranscript, setFinalTranscript] = useState('');

    // Ref to track accumulated text for web speech engine
    const accumulatedTextRef = useRef('');

    // Custom setFinalTranscript that also updates the accumulated ref
    const handleSetFinalTranscript = useCallback((text: string | ((prev: string) => string)) => {
        setFinalTranscript((prev) => {
            const newText = typeof text === 'function' ? text(prev) : text;
            accumulatedTextRef.current = newText;
            return newText;
        });
    }, []);

    const webSpeechHandlers = {
        setStatus,
        setError,
        setInterimTranscript,
        setFinalTranscript: handleSetFinalTranscript,
    };

    const whisperHandlers = {
        setStatus,
        setError,
        setFinalTranscript: handleSetFinalTranscript,
    };

    const webSpeech = useWebSpeechEngine(lang, webSpeechHandlers);
    const whisper = useWhisperEngine(whisperWsUrl, whisperHandlers);

    // Destructure stable callbacks (each created with useCallback(fn, []))
    // to avoid unstable object references in dependency arrays
    const { startWebSpeech, stopWebSpeech, cleanup: cleanupWebSpeech, resetAccumulated } = webSpeech;
    const { startWhisper, stopWhisper, cleanup: cleanupWhisper } = whisper;

    const startListening = useCallback(() => {
        if (engine === 'web-speech') startWebSpeech();
        else if (engine === 'whisper') startWhisper();
    }, [engine, startWebSpeech, startWhisper]);

    const stopListening = useCallback(() => {
        if (engine === 'web-speech') stopWebSpeech();
        else if (engine === 'whisper') stopWhisper();
    }, [engine, stopWebSpeech, stopWhisper]);

    const resetTranscript = useCallback(() => {
        accumulatedTextRef.current = '';
        resetAccumulated();
        setFinalTranscript('');
        setInterimTranscript('');
        setError(null);
    }, [resetAccumulated]);

    // Cleanup on unmount only — cleanup callbacks are stable (useCallback with [] deps)
    useEffect(() => {
        return () => {
            cleanupWebSpeech();
            cleanupWhisper();
        };
    }, [cleanupWebSpeech, cleanupWhisper]);

    return {
        engine,
        isSupported,
        status,
        error,
        interimTranscript,
        finalTranscript,
        startListening,
        stopListening,
        resetTranscript,
    };
}
