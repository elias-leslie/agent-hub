"use client";

import { KeyboardEvent, useState, useEffect, useCallback, useRef } from "react";
import { useVoice } from "@agent-hub/passport-client";
import type { StreamStatus } from "@/types/chat";
import { cn } from "@/lib/utils";
import type { ModelOption } from "./model-options";
import { MODEL_OPTIONS } from "./model-options";
import { MentionChip } from "./mention-chip";
import { MentionPopup } from "./mention-popup";
import { useMentionPopup } from "./use-mention-popup";
import { useVoiceInput } from "./use-voice-input";
import {
  ModelTriggerButton,
  StopSpeakingButton,
  MicButton,
  StopButton,
  SendButton,
} from "./input-buttons";

interface MessageInputProps {
  onSend: (message: string, targetModels?: string[]) => void;
  onCancel: () => void;
  status: StreamStatus;
  disabled?: boolean;
  voiceWsUrl?: string;
  ttsBaseUrl?: string;
  onVoiceSend?: () => void;
  onSpeakTextReady?: (speakText: (text: string) => Promise<void>) => void;
  editingMessage?: { id: string; content: string; model?: string } | null;
  onEditCancel?: () => void;
}

export function MessageInput({
  onSend,
  onCancel,
  status,
  disabled = false,
  voiceWsUrl,
  ttsBaseUrl,
  onVoiceSend,
  onSpeakTextReady,
  editingMessage,
  onEditCancel,
}: MessageInputProps) {
  const [input, setInput] = useState("");
  const [isInputFocused, setIsInputFocused] = useState(false);
  const [selectedModels, setSelectedModels] = useState<ModelOption[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inputWrapperRef = useRef<HTMLDivElement>(null);

  const {
    showMentionPopup,
    mentionFilter,
    mentionSelectedIndex,
    filteredModels,
    triggerMentionPopup,
    closeMentionPopup,
    updateMentionFilter,
    handleMentionNavigation,
  } = useMentionPopup(input, selectedModels);

  useEffect(() => {
    if (editingMessage) {
      setInput(editingMessage.content);
      if (editingMessage.model) {
        const model = MODEL_OPTIONS.find((m) => m.model === editingMessage.model);
        if (model) setSelectedModels([model]);
      }
      textareaRef.current?.focus();
    }
  }, [editingMessage]);

  const handleTranscript = useCallback(
    (text: string) => {
      if (text.trim()) {
        const targetModels = selectedModels.length > 0 ? selectedModels.map((m) => m.model) : undefined;
        onSend(text.trim(), targetModels);
        onVoiceSend?.();
        setSelectedModels([]);
      }
    },
    [onSend, onVoiceSend, selectedModels]
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

  useEffect(() => {
    if (voiceWsUrl && !isConnected) {
      connect(voiceWsUrl);
    }
  }, [voiceWsUrl, isConnected, connect]);

  useEffect(() => {
    if (speakText && onSpeakTextReady) {
      onSpeakTextReady(speakText);
    }
  }, [speakText, onSpeakTextReady]);

  const { handleMicClick } = useVoiceInput({
    isInputFocused,
    isSpeaking,
    isRecording,
    status,
    disabled,
    voiceWsUrl,
    startRecording,
    stopRecording,
    stopSpeaking,
  });

  const isStreaming = status === "streaming" || status === "cancelling";
  const isCancelling = status === "cancelling";
  const canSend = !isStreaming && !disabled && input.trim().length > 0;
  const canCancel = status === "streaming";
  const canRecord = !!(voiceWsUrl && !isStreaming && !disabled);

  const handleSend = () => {
    if (!canSend) return;
    const targetModels = selectedModels.length > 0 ? selectedModels.map((m) => m.model) : undefined;
    onSend(input.trim(), targetModels);
    setInput("");
    setSelectedModels([]);
  };

  const selectModel = useCallback(
    (model: ModelOption) => {
      setSelectedModels((prev) => [...prev, model]);
      closeMentionPopup();
      const currentText = input;
      const atIndex = currentText.lastIndexOf("@");
      if (atIndex !== -1) {
        setInput(currentText.slice(0, atIndex).trimEnd() + (atIndex > 0 ? " " : ""));
      }
      textareaRef.current?.focus();
    },
    [input, closeMentionPopup]
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    setInput(value);
    updateMentionFilter(value);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (handleMentionNavigation(e.key)) {
      e.preventDefault();
      return;
    }

    if (showMentionPopup && (e.key === "Enter" || e.key === "Tab")) {
      e.preventDefault();
      if (filteredModels[mentionSelectedIndex]) {
        selectModel(filteredModels[mentionSelectedIndex]);
      }
      return;
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }

    if (e.key === "Escape" && editingMessage && onEditCancel) {
      e.preventDefault();
      onEditCancel();
      setInput("");
      setSelectedModels([]);
    }
  };

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 p-4">
      {editingMessage && (
        <div className="flex items-center justify-between mb-2 px-1">
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
            Editing message
          </span>
          {onEditCancel && (
            <button
              onClick={() => {
                onEditCancel();
                setInput("");
                setSelectedModels([]);
              }}
              className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              Cancel
            </button>
          )}
        </div>
      )}

      <div className="flex items-end gap-2" ref={inputWrapperRef}>
        <div className="relative flex-1">
          {showMentionPopup && (
            <MentionPopup
              options={filteredModels}
              selectedIndex={mentionSelectedIndex}
              onSelect={selectModel}
              filter={mentionFilter}
            />
          )}

          {selectedModels.length > 0 && (
            <div className="absolute left-3 top-2 z-10 flex gap-1 flex-wrap max-w-[60%]">
              {selectedModels.map((model) => (
                <MentionChip
                  key={model.alias}
                  model={model}
                  onRemove={() => setSelectedModels((prev) => prev.filter((m) => m.alias !== model.alias))}
                />
              ))}
            </div>
          )}

          <textarea
            ref={textareaRef}
            data-testid="chat-input"
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsInputFocused(true)}
            onBlur={() => setIsInputFocused(false)}
            placeholder={
              isStreaming
                ? "Waiting for response..."
                : isRecording
                  ? "Recording... release spacebar to send"
                  : selectedModels.length > 0
                    ? "Type your message..."
                    : "Type a message or @ to select model..."
            }
            disabled={isStreaming || disabled}
            rows={1}
            className={cn(
              "w-full resize-none rounded-xl border border-gray-300 dark:border-gray-600",
              "bg-white dark:bg-gray-800 px-4 py-2.5",
              "focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              "min-h-[44px] max-h-[120px]",
              "transition-all duration-200",
              selectedModels.length > 0 && (selectedModels.length === 1 ? "pl-[140px]" : "pl-[280px]")
            )}
            style={{
              height: "auto",
              overflow: input.split("\n").length > 3 ? "auto" : "hidden",
            }}
          />
        </div>

        {!isStreaming && !voiceWsUrl && (
          <ModelTriggerButton onClick={triggerMentionPopup} disabled={disabled} />
        )}

        {voiceWsUrl && (
          <>
            {isSpeaking && <StopSpeakingButton onClick={stopSpeaking} />}
            <MicButton
              isRecording={isRecording}
              canRecord={canRecord}
              isSpeaking={isSpeaking}
              onClick={handleMicClick}
            />
          </>
        )}

        {isStreaming ? (
          <StopButton onClick={onCancel} canCancel={canCancel} isCancelling={isCancelling} />
        ) : (
          <SendButton onClick={handleSend} canSend={canSend} />
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
