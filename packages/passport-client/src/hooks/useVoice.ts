"use client";

import { useState, useRef, useCallback } from 'react';

export function useVoice({
    onTranscript,
    onResponse
}: {
    onTranscript?: (text: string) => void;
    onResponse?: (text: string) => void;
} = {}) {
    const [isRecording, setIsRecording] = useState(false);
    const [isPlaying, setIsPlaying] = useState(false);
    const [isConnected, setIsConnected] = useState(false);

    const wsRef = useRef<WebSocket | null>(null);
    const audioContextRef = useRef<AudioContext | null>(null);
    const streamRef = useRef<MediaStream | null>(null);
    const processorRef = useRef<ScriptProcessorNode | null>(null); // Fallback if AudioWorklet tricky in lib

    // Connect to Agent Hub
    const connect = useCallback((wsUrl: string) => {
        if (wsRef.current) return;

        console.log('Voice Client Connecting to:', wsUrl);
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => setIsConnected(true);
        ws.onclose = () => setIsConnected(false);
        ws.onmessage = async (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === 'transcript') {
                onTranscript?.(msg.data);
            } else if (msg.type === 'response') {
                onResponse?.(msg.data);
                // If we get text response, we might expect audio next
            } else if (msg.type === 'audio') {
                // Play Audio
                setIsPlaying(true);
                await playAudio(msg.data);
                setIsPlaying(false);
            }
        };
    }, [onTranscript, onResponse]);

    // Audio Playback
    const playAudio = async (base64Data: string) => {
        if (!audioContextRef.current) audioContextRef.current = new AudioContext();
        const ctx = audioContextRef.current;

        // Base64 -> ArrayBuffer
        const binaryString = window.atob(base64Data);
        const len = binaryString.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }

        const audioBuffer = await ctx.decodeAudioData(bytes.buffer);
        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(ctx.destination);
        source.start(0);

        return new Promise<void>((resolve) => {
            source.onended = () => resolve();
        });
    };

    const startRecording = useCallback(async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            streamRef.current = stream;

            if (!audioContextRef.current) audioContextRef.current = new AudioContext({ sampleRate: 16000 });
            const ctx = audioContextRef.current;

            const source = ctx.createMediaStreamSource(stream);
            // Deprecated but easiest for portable library without loading external worklet file via URL
            const processor = ctx.createScriptProcessor(4096, 1, 1);

            processor.onaudioprocess = (e) => {
                if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

                const inputData = e.inputBuffer.getChannelData(0);
                // Downsample/Convert to Int16
                const int16Array = new Int16Array(inputData.length);
                for (let i = 0; i < inputData.length; i++) {
                    let s = Math.max(-1, Math.min(1, inputData[i]));
                    int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }

                // Send
                const blob = new Blob([int16Array.buffer], { type: 'application/octet-stream' });
                const reader = new FileReader();
                reader.onloadend = () => {
                    const base64 = (reader.result as string).split(',')[1];
                    wsRef.current?.send(JSON.stringify({ type: 'audio', data: base64 }));
                };
                reader.readAsDataURL(blob);
            };

            source.connect(processor);
            processor.connect(ctx.destination); // Mute loopback if needed, but required for chrome to pump events

            processorRef.current = processor;
            wsRef.current?.send(JSON.stringify({ type: 'control', action: 'start' }));
            setIsRecording(true);

        } catch (e) {
            console.error("Mic Error", e);
        }
    }, []);

    const stopRecording = useCallback(() => {
        streamRef.current?.getTracks().forEach(t => t.stop());
        processorRef.current?.disconnect();
        wsRef.current?.send(JSON.stringify({ type: 'control', action: 'stop' }));
        setIsRecording(false);
    }, []);

    return {
        isRecording,
        isPlaying,
        isConnected,
        connect,
        startRecording,
        stopRecording
    };
}
