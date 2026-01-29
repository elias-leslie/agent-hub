import { useEffect, useRef, useCallback } from "react";
import type { StreamStatus } from "@/types/chat";

interface UseVoiceInputProps {
  isInputFocused: boolean;
  isSpeaking: boolean;
  isRecording: boolean;
  status: StreamStatus;
  disabled: boolean;
  voiceWsUrl?: string;
  startRecording: () => void;
  stopRecording: () => void;
  stopSpeaking: () => void;
}

export function useVoiceInput({
  isInputFocused,
  isSpeaking,
  isRecording,
  status,
  disabled,
  voiceWsUrl,
  startRecording,
  stopRecording,
  stopSpeaking,
}: UseVoiceInputProps) {
  const isSpaceHeldRef = useRef(false);

  useEffect(() => {
    if (!voiceWsUrl) return;

    const handleKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape" && isSpeaking) {
        e.preventDefault();
        stopSpeaking();
        return;
      }

      if (e.code === "Space") {
        if (isInputFocused) return;
        e.preventDefault();
        if (isSpeaking) {
          stopSpeaking();
          return;
        }
        if (isSpaceHeldRef.current || isRecording) return;
        if (status === "streaming" || status === "cancelling" || disabled) return;
        isSpaceHeldRef.current = true;
        startRecording();
      }
    };

    const handleKeyUp = (e: globalThis.KeyboardEvent) => {
      if (e.code === "Space" && isSpaceHeldRef.current) {
        isSpaceHeldRef.current = false;
        if (isRecording) {
          stopRecording();
        }
      }
    };

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

  return { handleMicClick };
}
