"use client";

import { useState, useRef, useCallback, useEffect } from 'react';

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

// SSR-safe SpeechRecognition detection
function getSpeechRecognitionCtor(): (new () => SpeechRecognition) | null {
    if (typeof window === 'undefined') return null;
    return (window.SpeechRecognition ?? window.webkitSpeechRecognition) ?? null;
}

function resolveEngine(
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
function mapSpeechError(error: string): TranscriptionError {
    switch (error) {
        case 'not-allowed': return 'not-allowed';
        case 'no-speech': return 'no-speech';
        case 'network': return 'network';
        case 'aborted': return 'aborted';
        default: return 'not-supported';
    }
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

    // Web Speech refs
    const recognitionRef = useRef<SpeechRecognition | null>(null);
    const isListeningRef = useRef(false);
    // Self-reference for auto-restart with fresh instances
    const startWebSpeechRef = useRef<() => void>(null);
    // All accumulated finalized text across recognition instances
    const accumulatedTextRef = useRef('');

    // Whisper refs
    const wsRef = useRef<WebSocket | null>(null);
    const audioContextRef = useRef<AudioContext | null>(null);
    const streamRef = useRef<MediaStream | null>(null);
    const processorRef = useRef<ScriptProcessorNode | null>(null);

    // -- Web Speech engine --
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
    }, [SpeechRecognition, lang]);

    // Keep ref in sync for self-referencing auto-restart
    startWebSpeechRef.current = startWebSpeech;

    const stopWebSpeech = useCallback(() => {
        isListeningRef.current = false;
        recognitionRef.current?.stop();
    }, []);

    // -- Whisper engine (Agent Hub WebSocket) --
    const startWhisper = useCallback(async () => {
        if (!whisperWsUrl) {
            setError('whisper-unavailable');
            setStatus('error');
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            streamRef.current = stream;

            // Build WS URL with mode=transcribe
            const separator = whisperWsUrl.includes('?') ? '&' : '?';
            const wsUrl = `${whisperWsUrl}${separator}mode=transcribe`;
            const ws = new WebSocket(wsUrl);
            wsRef.current = ws;

            ws.onopen = () => {
                // Start audio capture once connected
                const ctx = new AudioContext({ sampleRate: 16000 });
                audioContextRef.current = ctx;

                const source = ctx.createMediaStreamSource(stream);
                const processor = ctx.createScriptProcessor(4096, 1, 1);

                processor.onaudioprocess = (e) => {
                    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
                    const inputData = e.inputBuffer.getChannelData(0);
                    const int16Array = new Int16Array(inputData.length);
                    for (let i = 0; i < inputData.length; i++) {
                        const s = Math.max(-1, Math.min(1, inputData[i]));
                        int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                    }
                    const blob = new Blob([int16Array.buffer], { type: 'application/octet-stream' });
                    const reader = new FileReader();
                    reader.onloadend = () => {
                        const base64 = (reader.result as string).split(',')[1];
                        wsRef.current?.send(JSON.stringify({ type: 'audio', data: base64 }));
                    };
                    reader.readAsDataURL(blob);
                };

                source.connect(processor);
                processor.connect(ctx.destination);
                processorRef.current = processor;

                ws.send(JSON.stringify({ type: 'control', action: 'start' }));
                setStatus('listening');
            };

            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                if (msg.type === 'transcript') {
                    setFinalTranscript((prev) => prev ? `${prev} ${msg.data}` : msg.data);
                    setStatus('idle');
                }
            };

            ws.onerror = () => {
                setError('whisper-unavailable');
                setStatus('error');
            };

            ws.onclose = () => {
                setStatus((prev) => prev === 'error' ? prev : 'idle');
            };

            setError(null);
            setStatus('listening');
        } catch (e) {
            // getUserMedia denied
            if (e instanceof DOMException && e.name === 'NotAllowedError') {
                setError('not-allowed');
            } else {
                setError('network');
            }
            setStatus('error');
        }
    }, [whisperWsUrl]);

    const stopWhisper = useCallback(() => {
        // Stop audio capture
        streamRef.current?.getTracks().forEach(t => t.stop());
        streamRef.current = null;
        processorRef.current?.disconnect();
        processorRef.current = null;

        // Tell server to process
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'control', action: 'stop' }));
            setStatus('processing');
        }

        // Close audio context
        audioContextRef.current?.close();
        audioContextRef.current = null;
    }, []);

    // -- Public API --
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
        setFinalTranscript('');
        setInterimTranscript('');
        setError(null);
    }, []);

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            isListeningRef.current = false;
            recognitionRef.current?.abort();
            streamRef.current?.getTracks().forEach(t => t.stop());
            processorRef.current?.disconnect();
            wsRef.current?.close();
            audioContextRef.current?.close();
        };
    }, []);

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
