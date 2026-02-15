import { useRef, useCallback } from 'react';
import type { TranscriptionStatus, TranscriptionError } from './types'

export interface WhisperEngineHandlers {
    setStatus: (status: TranscriptionStatus | ((prev: TranscriptionStatus) => TranscriptionStatus)) => void
    setError: (error: TranscriptionError) => void
    setFinalTranscript: (text: string | ((prev: string) => string)) => void
}

export interface WhisperEngineReturn {
    startWhisper: () => Promise<void>
    stopWhisper: () => void
    cleanup: () => void
}

export function useWhisperEngine(
    whisperWsUrl: string | undefined,
    handlers: WhisperEngineHandlers
): WhisperEngineReturn {
    const { setStatus, setError, setFinalTranscript } = handlers;

    const wsRef = useRef<WebSocket | null>(null);
    const audioContextRef = useRef<AudioContext | null>(null);
    const streamRef = useRef<MediaStream | null>(null);
    const processorRef = useRef<ScriptProcessorNode | null>(null);

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
    }, [whisperWsUrl, setStatus, setError, setFinalTranscript]);

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
    }, [setStatus]);

    const cleanup = useCallback(() => {
        streamRef.current?.getTracks().forEach(t => t.stop());
        processorRef.current?.disconnect();
        wsRef.current?.close();
        audioContextRef.current?.close();
    }, []);

    return { startWhisper, stopWhisper, cleanup };
}
