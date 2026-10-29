import type { ChangeEvent, KeyboardEvent, ReactNode, RefObject } from "react";
import type { ChatVoice } from "../../types/voice";
import { cn } from "../../lib/utils";
import { MentionChip } from "../mention-chip";
import { MentionPopup } from "../mention-popup";
import { MicButton } from "../input-buttons";
import { SpeakerButton } from "../speaker-button";
import type { ModelOption } from "../use-models";
import { BAD, tint } from "./colors";

interface TranscriptComposerProps {
  input: string;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  inputWrapperRef: RefObject<HTMLDivElement | null>;
  showMentionPopup: boolean;
  mentionFilter: string;
  mentionSelectedIndex: number;
  filteredModels: ModelOption[];
  selectedModels: ModelOption[];
  isStreaming: boolean;
  isCancelling: boolean;
  canSend: boolean;
  canCancel: boolean;
  locked: boolean;
  allowQueue: boolean;
  recording: boolean;
  voice?: ChatVoice;
  canRecord: boolean;
  isSpeaking: boolean;
  editing: boolean;
  controls?: ReactNode;
  onChange: (event: ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onFocus: () => void;
  onBlur: () => void;
  onSend: () => void;
  onCancel: () => void;
  onSelectModel: (model: ModelOption) => void;
  onRemoveModel: (alias: string) => void;
  onMic: () => void;
  stopSpeaking: () => void;
  onEditCancel?: () => void;
}

const BUTTON =
  "inline-flex h-7 items-center rounded-md border px-2.5 text-[12.5px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50";

/**
 * The transcript layout's composer: one bordered box, a textarea, and a bar under it holding the host's controls
 * (the model select) and, on the right, Stop and Send. While a turn runs and the host queues follow-ups, Send reads
 * "Queue".
 */
export function TranscriptComposer(props: TranscriptComposerProps) {
  const { isStreaming, allowQueue, voice } = props;
  const placeholder = isStreaming
    ? allowQueue
      ? "Message — sent after the current turn"
      : "Waiting for the model…"
    : props.recording
      ? "Recording… release the space bar to send"
      : "Message";
  return (
    <div className="relative" ref={props.inputWrapperRef}>
      {props.editing && props.onEditCancel ? (
        <div className="mb-1 flex items-center justify-between px-1 text-xs text-muted-foreground">
          <span>Editing message</span>
          <button type="button" onClick={props.onEditCancel} className="hover:text-foreground">
            Cancel
          </button>
        </div>
      ) : null}
      {props.showMentionPopup ? (
        <MentionPopup
          options={props.filteredModels}
          selectedIndex={props.mentionSelectedIndex}
          onSelect={props.onSelectModel}
          filter={props.mentionFilter}
        />
      ) : null}
      <div
        data-testid="composer"
        className="rounded-[10px] border border-input bg-card transition-colors focus-within:border-ring/60"
      >
        <textarea
          ref={props.textareaRef}
          data-testid="chat-input"
          aria-label="Message"
          value={props.input}
          onChange={props.onChange}
          onKeyDown={props.onKeyDown}
          onFocus={props.onFocus}
          onBlur={props.onBlur}
          placeholder={placeholder}
          disabled={props.locked}
          rows={2}
          className="block max-h-40 min-h-[46px] w-full resize-none bg-transparent px-3 pb-1 pt-2.5 text-sm leading-6 text-foreground placeholder:text-muted-foreground focus:outline-none disabled:opacity-50"
        />
        <div className="flex flex-wrap items-center gap-2 px-2 pb-1.5 pt-0.5">
          {props.selectedModels.map((model) => (
            <MentionChip key={model.alias} model={model} onRemove={() => props.onRemoveModel(model.alias)} />
          ))}
          {props.controls}
          <span className="flex-1" />
          {voice?.speakerAvailable ? (
            <SpeakerButton
              ttsEnabled={voice.ttsEnabled}
              isSpeaking={props.isSpeaking}
              onToggle={() => voice.setTtsEnabled(!voice.ttsEnabled)}
              onStopSpeaking={props.stopSpeaking}
            />
          ) : null}
          {voice?.micAvailable ? (
            <MicButton isRecording={props.recording} canRecord={props.canRecord} isSpeaking={props.isSpeaking} onClick={props.onMic} />
          ) : null}
          {isStreaming ? (
            <button
              type="button"
              data-testid="stop-button"
              onClick={props.onCancel}
              disabled={!props.canCancel}
              aria-label="Stop generating"
              className={cn(BUTTON, props.isCancelling && "animate-pulse motion-reduce:animate-none")}
              style={{ color: BAD, borderColor: tint(BAD, 40), backgroundColor: tint(BAD, 14) }}
            >
              Stop
            </button>
          ) : null}
          {!isStreaming || allowQueue ? (
            <button
              type="button"
              data-testid="send-button"
              onClick={props.onSend}
              disabled={!props.canSend}
              aria-label={isStreaming ? "Queue message" : "Send message"}
              className={cn(BUTTON, "border-primary bg-primary text-primary-foreground hover:bg-primary/90")}
            >
              {isStreaming ? "Queue" : "Send"}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
