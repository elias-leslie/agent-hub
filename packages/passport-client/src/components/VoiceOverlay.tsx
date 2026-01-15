"use client";

import React, { useEffect } from 'react';
import { Mic, MicOff, X } from 'lucide-react';
import { useVoice } from '../hooks/useVoice';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export interface VoiceOverlayProps {
    wsUrl: string; // e.g., wss://api.agent-hub.dev/api/voice/ws
    initialIsOpen?: boolean;
}

export function VoiceOverlay({ wsUrl, initialIsOpen = false }: VoiceOverlayProps) {
    const [isOpen, setIsOpen] = React.useState(initialIsOpen);
    const [transcript, setTranscript] = React.useState('');
    const [lastResponse, setLastResponse] = React.useState('');

    const {
        isRecording,
        isPlaying,
        isConnected,
        connect,
        startRecording,
        stopRecording
    } = useVoice({
        onTranscript: (text) => setTranscript(text),
        onResponse: (text) => setLastResponse(text)
    });

    useEffect(() => {
        if (isOpen) {
            let finalUrl = wsUrl;
            if (wsUrl.startsWith('/')) {
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                finalUrl = `${protocol}//${window.location.host}${wsUrl}`;
            }
            connect(finalUrl);
        }
    }, [isOpen, wsUrl, connect]);

    if (!isOpen) {
        return (
            <button
                onClick={() => setIsOpen(true)}
                className="fixed bottom-6 right-6 p-4 bg-blue-600 hover:bg-blue-700 text-white rounded-full shadow-lg transition-transform hover:scale-110 z-[9999] flex items-center justify-center"
                title="Open Voice Assistant"
            >
                <Mic size={24} />
            </button>
        );
    }

    return (
        <div className="fixed bottom-6 right-6 w-80 bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl z-[9999] overflow-hidden flex flex-col font-sans text-slate-100">
            {/* Header */}
            <div className="flex items-center justify-between p-3 bg-slate-800 border-b border-slate-700">
                <div className="flex items-center gap-2">
                    <div className={cn("w-2 h-2 rounded-full", isConnected ? "bg-green-500" : "bg-red-500")} />
                    <span className="font-semibold text-sm">Passport Voice</span>
                </div>
                <button onClick={() => setIsOpen(false)} className="text-slate-400 hover:text-white">
                    <X size={18} />
                </button>
            </div>

            {/* Content */}
            <div className="p-4 flex-1 min-h-[200px] flex flex-col gap-3 overflow-y-auto max-h-[400px]">
                {lastResponse && (
                    <div className="bg-slate-800 p-3 rounded-xl rounded-tl-sm text-sm">
                        {lastResponse}
                    </div>
                )}
                {transcript && (
                    <div className="bg-blue-600 p-3 rounded-xl rounded-tr-sm text-sm self-end">
                        {transcript}
                    </div>
                )}
                {!lastResponse && !transcript && (
                    <div className="flex-1 flex items-center justify-center text-slate-500 text-sm italic">
                        Ready to help...
                    </div>
                )}
            </div>

            {/* Controls */}
            <div className="p-4 bg-slate-800/50 flex justify-center border-t border-slate-700">
                <button
                    onMouseDown={() => startRecording()}
                    onMouseUp={() => stopRecording()}
                    onTouchStart={() => startRecording()}
                    onTouchEnd={() => stopRecording()}
                    className={cn(
                        "w-16 h-16 rounded-full flex items-center justify-center transition-all shadow-lg",
                        isRecording
                            ? "bg-red-500 scale-110 shadow-red-500/50"
                            : isPlaying
                                ? "bg-purple-500 animate-pulse"
                                : "bg-blue-600 hover:bg-blue-500"
                    )}
                >
                    {isRecording ? <MicOff size={28} /> : <Mic size={28} />}
                </button>
            </div>
            <div className="text-center pb-2 text-[10px] text-slate-500">Hold to speak</div>
        </div>
    );
}
