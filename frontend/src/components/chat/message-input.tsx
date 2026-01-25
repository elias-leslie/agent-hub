"use client";

import {
  KeyboardEvent,
  useState,
  useEffect,
  useCallback,
  useRef,
  useMemo,
} from "react";
import { Send, Square, Mic, MicOff, VolumeX, X, Sparkles } from "lucide-react";
import { useVoice } from "@agent-hub/passport-client";
import type { StreamStatus } from "@/types/chat";
import { cn } from "@/lib/utils";

interface ModelOption {
  alias: string;
  model: string;
  hint: string;
  provider: "claude" | "gemini";
}

const MODEL_OPTIONS: ModelOption[] = [
  { alias: "sonnet", model: "claude-sonnet-4-5", hint: "Balanced", provider: "claude" },
  { alias: "opus", model: "claude-opus-4-5", hint: "Powerful", provider: "claude" },
  { alias: "haiku", model: "claude-haiku-3-5", hint: "Quick", provider: "claude" },
  { alias: "flash", model: "gemini-2.5-flash-preview-05-20", hint: "Fast", provider: "gemini" },
  { alias: "pro", model: "gemini-2.5-pro-preview-05-06", hint: "Reasoning", provider: "gemini" },
];

function MentionChip({
  model,
  onRemove,
}: {
  model: ModelOption;
  onRemove: () => void;
}) {
  const isClaudeProvider = model.provider === "claude";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 rounded-full text-sm font-medium",
        "transition-all duration-200 ease-out",
        "shadow-sm",
        isClaudeProvider
          ? "bg-gradient-to-r from-amber-100 to-orange-100 text-amber-800 border border-amber-200/60"
          : "bg-gradient-to-r from-blue-100 to-cyan-100 text-blue-800 border border-blue-200/60",
        isClaudeProvider
          ? "dark:from-amber-900/40 dark:to-orange-900/40 dark:text-amber-200 dark:border-amber-700/40"
          : "dark:from-blue-900/40 dark:to-cyan-900/40 dark:text-blue-200 dark:border-blue-700/40"
      )}
    >
      <span className="flex items-center gap-1">
        <span
          className={cn(
            "w-1.5 h-1.5 rounded-full",
            isClaudeProvider ? "bg-amber-500" : "bg-blue-500"
          )}
        />
        @{model.alias}
      </span>
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onRemove();
        }}
        className={cn(
          "p-0.5 rounded-full transition-colors duration-150",
          isClaudeProvider
            ? "hover:bg-amber-300/50 dark:hover:bg-amber-600/30"
            : "hover:bg-blue-300/50 dark:hover:bg-blue-600/30"
        )}
        aria-label={`Remove @${model.alias}`}
      >
        <X className="w-3 h-3" />
      </button>
    </span>
  );
}

function MentionPopup({
  options,
  selectedIndex,
  onSelect,
  filter,
}: {
  options: ModelOption[];
  selectedIndex: number;
  onSelect: (model: ModelOption) => void;
  filter: string;
}) {
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (popupRef.current && selectedIndex >= 0) {
      const selectedItem = popupRef.current.children[selectedIndex] as HTMLElement;
      selectedItem?.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex]);

  return (
    <div
      ref={popupRef}
      className={cn(
        "absolute bottom-full left-0 mb-2 z-50",
        "bg-white/95 dark:bg-gray-900/95 backdrop-blur-xl",
        "border border-gray-200/80 dark:border-gray-700/80",
        "rounded-xl shadow-xl shadow-black/10 dark:shadow-black/30",
        "py-2 min-w-[220px] max-h-[280px] overflow-y-auto",
        "animate-in fade-in slide-in-from-bottom-2 duration-200"
      )}
      role="listbox"
      aria-label="Select a model"
    >
      <div className="px-3 pb-2 mb-1 border-b border-gray-100 dark:border-gray-800">
        <span className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider">
          {filter ? `Matching "${filter}"` : "Select Model"}
        </span>
      </div>
      {options.map((option, index) => {
        const isSelected = index === selectedIndex;
        const isClaudeProvider = option.provider === "claude";

        return (
          <button
            key={option.alias}
            type="button"
            role="option"
            aria-selected={isSelected}
            onClick={() => onSelect(option)}
            className={cn(
              "w-full px-3 py-2.5 text-left flex items-center gap-3",
              "transition-all duration-150 ease-out",
              "focus:outline-none",
              isSelected
                ? isClaudeProvider
                  ? "bg-amber-50 dark:bg-amber-900/20"
                  : "bg-blue-50 dark:bg-blue-900/20"
                : "hover:bg-gray-50 dark:hover:bg-gray-800/50"
            )}
          >
            <span
              className={cn(
                "flex items-center justify-center w-8 h-8 rounded-lg text-sm font-bold",
                "transition-transform duration-150",
                isSelected && "scale-105",
                isClaudeProvider
                  ? "bg-gradient-to-br from-amber-400 to-orange-500 text-white"
                  : "bg-gradient-to-br from-blue-400 to-cyan-500 text-white"
              )}
            >
              {option.alias.charAt(0).toUpperCase()}
            </span>
            <div className="flex-1 min-w-0">
              <div
                className={cn(
                  "font-medium text-sm",
                  isClaudeProvider
                    ? "text-amber-700 dark:text-amber-300"
                    : "text-blue-700 dark:text-blue-300"
                )}
              >
                @{option.alias}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">
                {option.hint}
              </div>
            </div>
            {isSelected && (
              <span className="text-xs text-gray-400 dark:text-gray-500 font-mono">
                ↵
              </span>
            )}
          </button>
        );
      })}
      {options.length === 0 && (
        <div className="px-3 py-4 text-center text-sm text-gray-400 dark:text-gray-500">
          No matching models
        </div>
      )}
    </div>
  );
}

interface MessageInputProps {
  onSend: (message: string, targetModel?: string) => void;
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
  const [selectedModel, setSelectedModel] = useState<ModelOption | null>(null);
  const [showMentionPopup, setShowMentionPopup] = useState(false);
  const [mentionFilter, setMentionFilter] = useState("");
  const [mentionSelectedIndex, setMentionSelectedIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isSpaceHeldRef = useRef(false);
  const inputWrapperRef = useRef<HTMLDivElement>(null);

  const filteredModels = useMemo(() => {
    if (!mentionFilter) return MODEL_OPTIONS;
    const lowerFilter = mentionFilter.toLowerCase();
    return MODEL_OPTIONS.filter(
      (m) =>
        m.alias.toLowerCase().includes(lowerFilter) ||
        m.hint.toLowerCase().includes(lowerFilter)
    );
  }, [mentionFilter]);

  useEffect(() => {
    setMentionSelectedIndex(0);
  }, [filteredModels]);

  useEffect(() => {
    if (editingMessage) {
      setInput(editingMessage.content);
      if (editingMessage.model) {
        const model = MODEL_OPTIONS.find((m) => m.model === editingMessage.model);
        if (model) setSelectedModel(model);
      }
      textareaRef.current?.focus();
    }
  }, [editingMessage]);

  const handleTranscript = useCallback(
    (text: string) => {
      if (text.trim()) {
        onSend(text.trim(), selectedModel?.model);
        onVoiceSend?.();
        setSelectedModel(null);
      }
    },
    [onSend, onVoiceSend, selectedModel]
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

  const isStreaming = status === "streaming" || status === "cancelling";
  const isCancelling = status === "cancelling";
  const canSend = !isStreaming && !disabled && input.trim().length > 0;
  const canCancel = status === "streaming";
  const canRecord = voiceWsUrl && !isStreaming && !disabled;

  const handleSend = () => {
    if (!canSend) return;
    onSend(input.trim(), selectedModel?.model);
    setInput("");
    setSelectedModel(null);
  };

  const selectModel = useCallback((model: ModelOption) => {
    setSelectedModel(model);
    setShowMentionPopup(false);
    setMentionFilter("");
    const currentText = input;
    const atIndex = currentText.lastIndexOf("@");
    if (atIndex !== -1) {
      setInput(currentText.slice(0, atIndex).trimEnd() + (atIndex > 0 ? " " : ""));
    }
    textareaRef.current?.focus();
  }, [input]);

  const triggerMentionPopup = useCallback(() => {
    setShowMentionPopup(true);
    setMentionFilter("");
    setMentionSelectedIndex(0);
    textareaRef.current?.focus();
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    setInput(value);

    const atMatch = value.match(/@(\w*)$/);
    if (atMatch) {
      setShowMentionPopup(true);
      setMentionFilter(atMatch[1]);
    } else if (showMentionPopup && !value.includes("@")) {
      setShowMentionPopup(false);
      setMentionFilter("");
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (showMentionPopup) {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setMentionSelectedIndex((prev) =>
            prev < filteredModels.length - 1 ? prev + 1 : 0
          );
          return;
        case "ArrowUp":
          e.preventDefault();
          setMentionSelectedIndex((prev) =>
            prev > 0 ? prev - 1 : filteredModels.length - 1
          );
          return;
        case "Enter":
          e.preventDefault();
          if (filteredModels[mentionSelectedIndex]) {
            selectModel(filteredModels[mentionSelectedIndex]);
          }
          return;
        case "Tab":
          e.preventDefault();
          if (filteredModels[mentionSelectedIndex]) {
            selectModel(filteredModels[mentionSelectedIndex]);
          }
          return;
        case "Escape":
          e.preventDefault();
          setShowMentionPopup(false);
          setMentionFilter("");
          return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }

    if (e.key === "Escape" && editingMessage && onEditCancel) {
      e.preventDefault();
      onEditCancel();
      setInput("");
      setSelectedModel(null);
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
                setSelectedModel(null);
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

          {selectedModel && (
            <div className="absolute left-3 top-2 z-10">
              <MentionChip
                model={selectedModel}
                onRemove={() => setSelectedModel(null)}
              />
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
                  : selectedModel
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
              selectedModel && "pl-[140px]"
            )}
            style={{
              height: "auto",
              overflow: input.split("\n").length > 3 ? "auto" : "hidden",
            }}
          />
        </div>

        {!isStreaming && !voiceWsUrl && (
          <button
            data-testid="model-trigger"
            onClick={triggerMentionPopup}
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
        )}

        {voiceWsUrl && (
          <>
            {isSpeaking && (
              <button
                data-testid="stop-speaking-button"
                onClick={stopSpeaking}
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
            )}

            <button
              data-testid="mic-button"
              onClick={handleMicClick}
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
        ) : (
          <button
            data-testid="send-button"
            onClick={handleSend}
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
