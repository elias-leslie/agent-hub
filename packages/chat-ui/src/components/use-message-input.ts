"use client";

import { useState, useEffect, useCallback, useRef, KeyboardEvent } from "react";
import type { ChatHubClient } from "../client";
import type { StreamStatus } from "../types/chat";
import type { ChatVoice } from "../types/voice";
import type { ModelOption } from "./use-models";
import { useModels } from "./use-models";
import { useMentionPopup } from "./use-mention-popup";
import { usePromptHistory } from "./use-prompt-history";
import { useVoiceInput } from "./use-voice-input";

export interface MessageInputProps {
  /** Agent slug — scopes the up/down prompt-history recall per agent. */
  agentSlug?: string;
  onSend: (message: string, targetModels?: string[]) => void;
  onCancel: () => void;
  status: StreamStatus;
  disabled?: boolean;
  /** Voice input and output, from `useChatVoice` in `@agent-hub/chat-ui/voice`. Without it the input has no mic or speaker. */
  voice?: ChatVoice;
  onVoiceSend?: () => void;
  editingMessage?: { id: string; content: string; model?: string } | null;
  onEditCancel?: () => void;
  compact?: boolean;
  /** Pre-fill the input with a prompt (e.g., from URL deep-link). Applied once on mount. */
  initialPrompt?: string;
  /** The Agent Hub client for the model list behind @mentions; falls back to a `ChatClientProvider`. */
  client?: ChatHubClient | null;
  allowModelMentions?: boolean;
  /** The host queues a message sent during a turn: the input stays enabled while the turn streams and Send sits next to Stop. */
  allowQueue?: boolean;
}

export function useMessageInput(props: MessageInputProps) {
  const {
    agentSlug,
    onSend,
    status,
    disabled = false,
    voice,
    onVoiceSend,
    editingMessage,
    onEditCancel,
    initialPrompt,
    client,
    allowModelMentions = true,
  } = props;

  const [input, setInput] = useState(initialPrompt || "");
  const [isInputFocused, setIsInputFocused] = useState(false);
  const [selectedModels, setSelectedModels] = useState<ModelOption[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inputWrapperRef = useRef<HTMLDivElement>(null);
  const allModels = useModels(client, { enabled: allowModelMentions });

  const {
    showMentionPopup,
    mentionFilter,
    mentionSelectedIndex,
    filteredModels,
    triggerMentionPopup,
    closeMentionPopup,
    updateMentionFilter,
    handleMentionNavigation,
  } = useMentionPopup(input, selectedModels, allModels);

  const {
    record: recordHistory,
    resetCursor: resetHistoryCursor,
    recallPrevious,
    recallNext,
  } = usePromptHistory(agentSlug);

  // Apply a recalled history entry and drop the caret at the end of the input.
  const applyRecalled = useCallback((value: string) => {
    setInput(value);
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (el) {
        el.selectionStart = el.selectionEnd = el.value.length;
      }
    });
  }, []);

  useEffect(() => {
    if (editingMessage) {
      setInput(editingMessage.content);
      if (editingMessage.model) {
        const model = allModels.find((m) => m.id === editingMessage.model);
        if (model) setSelectedModels([model]);
      }
      textareaRef.current?.focus();
    }
  }, [editingMessage]);

  const handleTranscript = useCallback(
    (text: string) => {
      if (text.trim()) {
        const targetModels = selectedModels.length > 0 ? selectedModels.map((m) => m.id) : undefined;
        onSend(text.trim(), targetModels);
        onVoiceSend?.();
        setSelectedModels([]);
      }
    },
    [onSend, onVoiceSend, selectedModels]
  );

  // A finished recording is sent like typed text.
  const setTranscriptHandler = voice?.setTranscriptHandler;
  useEffect(() => {
    if (!setTranscriptHandler) return;
    setTranscriptHandler(handleTranscript);
    return () => setTranscriptHandler(null);
  }, [setTranscriptHandler, handleTranscript]);

  const micAvailable = voice?.micAvailable ?? false;
  const isRecording = voice?.isRecording ?? false;
  const isSpeaking = voice?.isSpeaking ?? false;
  const noop = useCallback(() => undefined, []);

  const { handleMicClick } = useVoiceInput({
    isInputFocused,
    isSpeaking,
    isRecording,
    status,
    disabled,
    voiceEnabled: micAvailable,
    startRecording: voice?.startRecording ?? noop,
    stopRecording: voice?.stopRecording ?? noop,
    stopSpeaking: voice?.stopSpeaking ?? noop,
  });

  const isStreaming = status === "streaming" || status === "cancelling" || status === "reconnecting";
  const isCancelling = status === "cancelling";
  // Allow sending during streaming — this triggers interrupt-and-send (steering)
  const canSend = !disabled && input.trim().length > 0 && status !== "cancelling";
  const canCancel = status === "streaming" || status === "reconnecting";
  const canRecord = micAvailable && !isStreaming && !disabled;

  const handleSend = useCallback(() => {
    if (!canSend) return;
    const targetModels = selectedModels.length > 0 ? selectedModels.map((m) => m.id) : undefined;
    const trimmed = input.trim();
    recordHistory(trimmed);
    onSend(trimmed, targetModels);
    setInput("");
    setSelectedModels([]);
  }, [canSend, selectedModels, onSend, input, recordHistory]);

  const selectModel = useCallback(
    (model: ModelOption) => {
      setSelectedModels((prev) => [...prev, model]);
      closeMentionPopup();
      const atIndex = input.lastIndexOf("@");
      if (atIndex !== -1) {
        setInput(input.slice(0, atIndex).trimEnd() + (atIndex > 0 ? " " : ""));
      }
      textareaRef.current?.focus();
    },
    [input, closeMentionPopup]
  );

  const removeModel = useCallback((alias: string) => {
    setSelectedModels((prev) => prev.filter((m) => m.alias !== alias));
  }, []);

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    setInput(value);
    // User edited the draft directly — stop browsing history.
    resetHistoryCursor();
    updateMentionFilter(value);
  }, [updateMentionFilter, resetHistoryCursor]);

  const cancelEditing = useCallback(() => {
    onEditCancel?.();
    setInput("");
    setSelectedModels([]);
  }, [onEditCancel]);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (allowModelMentions && handleMentionNavigation(e.key)) {
      e.preventDefault();
      return;
    }

    if (allowModelMentions && showMentionPopup && (e.key === "Enter" || e.key === "Tab")) {
      e.preventDefault();
      if (filteredModels[mentionSelectedIndex]) {
        selectModel(filteredModels[mentionSelectedIndex]);
      }
      return;
    }

    // Shell-style prompt history recall (only when the @mention popup is closed
    // and the caret is collapsed — multi-line editing/selection is unaffected).
    // ArrowUp recalls older entries when the caret is on the first line;
    // ArrowDown recalls newer ones when it is on the last line.
    if (!showMentionPopup && e.key === "ArrowUp") {
      const el = e.currentTarget;
      const caret = el.selectionStart ?? 0;
      if (el.selectionStart === el.selectionEnd && !input.slice(0, caret).includes("\n")) {
        const recalled = recallPrevious(input);
        if (recalled !== null) {
          e.preventDefault();
          applyRecalled(recalled);
          return;
        }
      }
    }

    if (!showMentionPopup && e.key === "ArrowDown") {
      const el = e.currentTarget;
      const caret = el.selectionStart ?? 0;
      if (el.selectionStart === el.selectionEnd && !input.slice(caret).includes("\n")) {
        const recalled = recallNext();
        if (recalled !== null) {
          e.preventDefault();
          applyRecalled(recalled);
          return;
        }
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }

    if (e.key === "Escape" && editingMessage && onEditCancel) {
      e.preventDefault();
      cancelEditing();
    }
  }, [allowModelMentions, handleMentionNavigation, showMentionPopup, filteredModels, mentionSelectedIndex, selectModel, handleSend, editingMessage, onEditCancel, cancelEditing, input, recallPrevious, recallNext, applyRecalled]);

  return {
    input,
    isInputFocused,
    selectedModels,
    textareaRef,
    inputWrapperRef,
    showMentionPopup,
    mentionFilter,
    mentionSelectedIndex,
    filteredModels,
    isStreaming,
    isCancelling,
    canSend,
    canCancel,
    canRecord,
    isRecording,
    isSpeaking,
    stopSpeaking: voice?.stopSpeaking ?? noop,
    triggerMentionPopup,
    handleSend,
    selectModel,
    removeModel,
    handleInputChange,
    handleKeyDown,
    cancelEditing,
    setIsInputFocused,
    handleMicClick,
  };
}
