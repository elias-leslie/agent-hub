"use client";

import { cn } from "../lib/utils";
import { MentionChip } from "./mention-chip";
import { MentionPopup } from "./mention-popup";
import { SpeakerButton } from "./speaker-button";
import {
  ModelTriggerButton,
  MicButton,
  StopButton,
  SendButton,
} from "./input-buttons";
import { useMessageInput } from "./use-message-input";
export type { MessageInputProps } from "./use-message-input";

export function MessageInput(props: import("./use-message-input").MessageInputProps) {
  const {
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
    stopSpeaking,
    triggerMentionPopup,
    handleSend,
    selectModel,
    removeModel,
    handleInputChange,
    handleKeyDown,
    cancelEditing,
    setIsInputFocused,
    handleMicClick,
  } = useMessageInput(props);

  const {
    onCancel,
    status,
    disabled = false,
    compact = false,
    voiceWsUrl,
    ttsBaseUrl,
    preferencesEndpoint,
    fetchFn,
    editingMessage,
    onEditCancel,
    onVoiceChange,
    onEnabledChange,
  } = props;

  return (
    <div className={cn("border-t border-gray-700", compact ? "p-2.5" : "p-4")}>
      {editingMessage && (
        <div className="flex items-center justify-between mb-2 px-1">
          <span className="text-xs font-medium text-gray-400">
            Editing message
          </span>
          {onEditCancel && (
            <button
              onClick={cancelEditing}
              className="text-xs text-gray-400 hover:text-gray-200"
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
                  onRemove={() => removeModel(model.alias)}
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
              "w-full resize-none rounded-xl border border-gray-600",
              "bg-gray-800 text-gray-100 placeholder:text-gray-500 px-4",
              compact ? "py-2 text-sm" : "py-2.5",
              "focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              compact ? "min-h-[40px] max-h-[108px]" : "min-h-[44px] max-h-[120px]",
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

        {ttsBaseUrl && (
          <SpeakerButton
            ttsBaseUrl={ttsBaseUrl}
            preferencesEndpoint={preferencesEndpoint}
            fetchFn={fetchFn}
            isSpeaking={isSpeaking}
            onStopSpeaking={stopSpeaking}
            onVoiceChange={onVoiceChange}
            onEnabledChange={onEnabledChange}
          />
        )}

        {voiceWsUrl && (
          <MicButton
            isRecording={isRecording}
            canRecord={canRecord}
            isSpeaking={isSpeaking}
            onClick={handleMicClick}
          />
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
