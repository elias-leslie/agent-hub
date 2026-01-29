import { Send, Square, Mic, MicOff, VolumeX, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

interface ModelTriggerButtonProps {
  onClick: () => void;
  disabled: boolean;
}

export function ModelTriggerButton({ onClick, disabled }: ModelTriggerButtonProps) {
  return (
    <button
      data-testid="model-trigger"
      onClick={onClick}
      disabled={disabled}
      aria-label="Select model"
      title="Select model (@)"
      className={cn(
        "flex items-center justify-center w-10 h-10 rounded-xl md:hidden",
        "transition-all duration-200",
        "bg-gray-100 hover:bg-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600",
        "text-gray-600 dark:text-gray-300",
        "disabled:opacity-50 disabled:cursor-not-allowed"
      )}
    >
      <Sparkles className="w-5 h-5" />
    </button>
  );
}

interface StopSpeakingButtonProps {
  onClick: () => void;
}

export function StopSpeakingButton({ onClick }: StopSpeakingButtonProps) {
  return (
    <button
      data-testid="stop-speaking-button"
      onClick={onClick}
      aria-label="Stop speaking"
      title="Stop speaking (Esc or Space)"
      className={cn(
        "flex items-center justify-center w-10 h-10 rounded-xl",
        "transition-colors duration-150",
        "bg-purple-500 hover:bg-purple-600 text-white cursor-pointer animate-pulse"
      )}
    >
      <VolumeX className="w-5 h-5" />
    </button>
  );
}

interface MicButtonProps {
  isRecording: boolean;
  canRecord: boolean;
  isSpeaking: boolean;
  onClick: () => void;
}

export function MicButton({ isRecording, canRecord, isSpeaking, onClick }: MicButtonProps) {
  return (
    <button
      data-testid="mic-button"
      onClick={onClick}
      disabled={!canRecord || isSpeaking}
      aria-label={isRecording ? "Stop recording" : "Start recording"}
      title={isRecording ? "Release to send" : "Voice input (hold spacebar)"}
      className={cn(
        "flex items-center justify-center w-10 h-10 rounded-xl",
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
  );
}

interface StopButtonProps {
  onClick: () => void;
  canCancel: boolean;
  isCancelling: boolean;
}

export function StopButton({ onClick, canCancel, isCancelling }: StopButtonProps) {
  return (
    <button
      data-testid="stop-button"
      onClick={onClick}
      disabled={!canCancel}
      aria-label="Stop generating"
      title="Stop generating"
      className={cn(
        "flex items-center justify-center w-10 h-10 rounded-xl",
        "transition-colors duration-150",
        canCancel
          ? "bg-red-500 hover:bg-red-600 text-white cursor-pointer"
          : "bg-gray-300 dark:bg-gray-600 text-gray-500 cursor-not-allowed",
        isCancelling && "animate-pulse"
      )}
    >
      <Square className="w-5 h-5" fill="currentColor" />
    </button>
  );
}

interface SendButtonProps {
  onClick: () => void;
  canSend: boolean;
}

export function SendButton({ onClick, canSend }: SendButtonProps) {
  return (
    <button
      data-testid="send-button"
      onClick={onClick}
      disabled={!canSend}
      aria-label="Send message"
      title="Send message"
      className={cn(
        "flex items-center justify-center w-10 h-10 rounded-xl",
        "transition-all duration-200",
        canSend
          ? "bg-blue-500 hover:bg-blue-600 text-white cursor-pointer shadow-md shadow-blue-500/30 hover:shadow-lg hover:shadow-blue-500/40"
          : "bg-gray-300 dark:bg-gray-600 text-gray-500 cursor-not-allowed"
      )}
    >
      <Send className="w-5 h-5" />
    </button>
  );
}
