"use client";

import {
  KeyboardEvent,
  useState,
  useEffect,
  useCallback,
  useRef,
} from "react";
import { Send, Square, Mic, MicOff, VolumeX } from "lucide-react";
import { useVoice } from "@agent-hub/passport-client";
import type { StreamStatus } from "@/types/chat";
import { cn } from "@/lib/utils";

interface MessageInputProps {
  onSend: (message: string) => void;
  onCancel: () => void;
  status: StreamStatus;
  disabled?: boolean;
  /** WebSocket URL for voice input. If provided, shows mic button */
  voiceWsUrl?: string;
  /** Base URL for TTS API (e.g., "http://localhost:8003") */
  ttsBaseUrl?: string;
  /** Callback when voice sends a message (for triggering TTS on response) */
  onVoiceSend?: () => void;
  /** Callback to expose speakText function to parent */
  onSpeakTextReady?: (speakText: (text: string) => Promise<void>) => void;
}

/**
 * Message input with Send/Stop button that toggles based on streaming state.
 *
 * - Shows Send button when idle
 * - Shows Stop button during streaming
 * - Pressing Stop triggers cancellation
 */
export function MessageInput({
  onSend,
  onCancel,
  status,
  disabled = false,
  voiceWsUrl,
  ttsBaseUrl,
  onVoiceSend,
  onSpeakTextReady,
}: MessageInputProps) {
  const [input, setInput] = useState("");
  const [isInputFocused, setIsInputFocused] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isSpaceHeldRef = useRef(false);

  // Voice input - when transcript received, send it as a message
  const handleTranscript = useCallback(
    (text: string) => {
      if (text.trim()) {
        onSend(text.trim());
        onVoiceSend?.(); // Notify parent that this was a voice message
      }
    },
    [onSend, onVoiceSend]
  );

  const {
    isRecording,
    isConnected,
    isSpeaking,
    connect,
    startRecording,
    stopRecording,
    speakText,
    stopSpeaking,
  } = useVoice({
    onTranscript: handleTranscript,
    ttsBaseUrl,
  });

  // Connect to voice WS when URL is provided
  useEffect(() => {
    if (voiceWsUrl && !isConnected) {
      connect(voiceWsUrl);
    }
  }, [voiceWsUrl, isConnected, connect]);

  // Expose speakText to parent
  useEffect(() => {
    if (speakText && onSpeakTextReady) {
      onSpeakTextReady(speakText);
    }
  }, [speakText, onSpeakTextReady]);

  // Push-to-talk: Spacebar controls when textarea is not focused
  useEffect(() => {
    if (!voiceWsUrl) return;

    const handleKeyDown = (e: globalThis.KeyboardEvent) => {
      // Escape always stops speaking
      if (e.key === "Escape" && isSpeaking) {
        e.preventDefault();
        stopSpeaking();
        return;
      }

      // Spacebar handling
      if (e.code === "Space") {
        // If textarea is focused, let normal typing happen
        if (isInputFocused) return;

        // Prevent default (scrolling)
        e.preventDefault();

        // If speaking, stop it
        if (isSpeaking) {
          stopSpeaking();
          return;
        }

        // If already held or already recording, ignore
        if (isSpaceHeldRef.current || isRecording) return;

        // Can't record while streaming
        if (status === "streaming" || status === "cancelling" || disabled) return;

        // Start recording (push-to-talk)
        isSpaceHeldRef.current = true;
        startRecording();
      }
    };

    const handleKeyUp = (e: globalThis.KeyboardEvent) => {
      if (e.code === "Space" && isSpaceHeldRef.current) {
        isSpaceHeldRef.current = false;
        // Only stop if we're actually recording
        if (isRecording) {
          stopRecording();
        }
      }
    };

    // Handle window blur (tab switch, etc) - stop recording if space was held
    const handleBlur = () => {
      if (isSpaceHeldRef.current) {
        isSpaceHeldRef.current = false;
        if (isRecording) {
          stopRecording();
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    window.addEventListener("blur", handleBlur);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
      window.removeEventListener("blur", handleBlur);
    };
  }, [
    voiceWsUrl,
    isInputFocused,
    isSpeaking,
    isRecording,
    status,
    disabled,
    startRecording,
    stopRecording,
    stopSpeaking,
  ]);

  const handleMicClick = useCallback(() => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  }, [isRecording, startRecording, stopRecording]);

  const isStreaming = status === "streaming" || status === "cancelling";
  const isCancelling = status === "cancelling";
  const canSend = !isStreaming && !disabled && input.trim().length > 0;
  const canCancel = status === "streaming";
  const canRecord = voiceWsUrl && !isStreaming && !disabled;

  const handleSend = () => {
    if (!canSend) return;
    onSend(input.trim());
    setInput("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 p-4">
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsInputFocused(true)}
          onBlur={() => setIsInputFocused(false)}
          placeholder={
            isStreaming
              ? "Waiting for response..."
              : isRecording
                ? "Recording... release spacebar to send"
                : "Type a message... (or hold spacebar to talk)"
          }
          disabled={isStreaming || disabled}
          rows={1}
          className={cn(
            "flex-1 resize-none rounded-lg border border-gray-300 dark:border-gray-600",
            "bg-white dark:bg-gray-800 px-4 py-2",
            "focus:outline-none focus:ring-2 focus:ring-blue-500",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "min-h-[40px] max-h-[120px]"
          )}
          style={{
            height: "auto",
            overflow: input.split("\n").length > 3 ? "auto" : "hidden",
          }}
        />

        {/* Voice controls - only shown when voice is enabled */}
        {voiceWsUrl && (
          <>
            {/* Speaking indicator / stop button */}
            {isSpeaking && (
              <button
                data-testid="stop-speaking-button"
                onClick={stopSpeaking}
                aria-label="Stop speaking"
                title="Stop speaking (Esc or Space)"
                className={cn(
                  "flex items-center justify-center w-10 h-10 rounded-lg",
                  "transition-colors duration-150",
                  "bg-purple-500 hover:bg-purple-600 text-white cursor-pointer animate-pulse"
                )}
              >
                <VolumeX className="w-5 h-5" />
              </button>
            )}

            {/* Mic button */}
            <button
              data-testid="mic-button"
              onClick={handleMicClick}
              disabled={!canRecord || isSpeaking}
              aria-label={isRecording ? "Stop recording" : "Start recording"}
              title={isRecording ? "Release to send" : "Voice input (hold spacebar)"}
              className={cn(
                "flex items-center justify-center w-10 h-10 rounded-lg",
                "transition-colors duration-150",
                isRecording
                  ? "bg-red-500 hover:bg-red-600 text-white cursor-pointer animate-pulse"
                  : canRecord && !isSpeaking
                    ? "bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 cursor-pointer"
                    : "bg-gray-300 dark:bg-gray-600 text-gray-500 cursor-not-allowed"
              )}
            >
              {isRecording ? (
                <MicOff className="w-5 h-5" />
              ) : (
                <Mic className="w-5 h-5" />
              )}
            </button>
          </>
        )}

        {isStreaming ? (
          <button
            data-testid="stop-button"
            onClick={onCancel}
            disabled={!canCancel}
            aria-label="Stop generating"
            title="Stop generating"
            className={cn(
              "flex items-center justify-center w-10 h-10 rounded-lg",
              "transition-colors duration-150",
              canCancel
                ? "bg-red-500 hover:bg-red-600 text-white cursor-pointer"
                : "bg-gray-300 dark:bg-gray-600 text-gray-500 cursor-not-allowed",
              isCancelling && "animate-pulse"
            )}
          >
            <Square className="w-5 h-5" fill="currentColor" />
          </button>
        ) : (
          <button
            data-testid="send-button"
            onClick={handleSend}
            disabled={!canSend}
            aria-label="Send message"
            title="Send message"
            className={cn(
              "flex items-center justify-center w-10 h-10 rounded-lg",
              "transition-colors duration-150",
              canSend
                ? "bg-blue-500 hover:bg-blue-600 text-white cursor-pointer"
                : "bg-gray-300 dark:bg-gray-600 text-gray-500 cursor-not-allowed"
            )}
          >
            <Send className="w-5 h-5" />
          </button>
        )}
      </div>

      {status === "error" && (
        <p className="mt-2 text-sm text-red-500">
          Connection error. Please try again.
        </p>
      )}
    </div>
  );
}
