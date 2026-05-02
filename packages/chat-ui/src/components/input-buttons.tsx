import { Send, Square, Mic, MicOff, VolumeX, Sparkles } from "lucide-react";
import { cn } from "../lib/utils";

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
        "bg-secondary text-secondary-foreground hover:bg-accent hover:text-accent-foreground",
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
        "bg-destructive hover:bg-destructive/90 text-white cursor-pointer animate-pulse"
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
          ? "bg-destructive hover:bg-destructive/90 text-white cursor-pointer animate-pulse"
          : canRecord && !isSpeaking
            ? "bg-secondary text-secondary-foreground hover:bg-accent hover:text-accent-foreground cursor-pointer"
            : "bg-muted text-muted-foreground cursor-not-allowed"
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
          ? "bg-destructive hover:bg-destructive/90 text-white cursor-pointer"
          : "bg-muted text-muted-foreground cursor-not-allowed",
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
          ? "bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer shadow-md shadow-primary/20 hover:shadow-lg hover:shadow-primary/25"
          : "bg-muted text-muted-foreground cursor-not-allowed"
      )}
    >
      <Send className="w-5 h-5" />
    </button>
  );
}
