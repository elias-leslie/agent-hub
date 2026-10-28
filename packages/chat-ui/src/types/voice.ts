/**
 * What the chat needs from a voice integration. The core package never imports a voice implementation: a host that
 * wants voice builds one with `useChatVoice` from `@agent-hub/chat-ui/voice` (or any object of this shape) and
 * passes it as `voice`. Without it the chat shows no mic or speaker.
 */
export interface ChatVoice {
  /** Show the mic button and the hold-space shortcut. */
  micAvailable: boolean;
  /** Show the speaker toggle. */
  speakerAvailable: boolean;
  isRecording: boolean;
  isSpeaking: boolean;
  ttsEnabled: boolean;
  selectedVoice: string;
  startRecording(): void;
  stopRecording(): void;
  speakText(text: string, voice?: string): Promise<void>;
  stopSpeaking(): void;
  setTtsEnabled(enabled: boolean): void;
  /** The chat registers where a finished recording's text goes. Pass null to unregister. */
  setTranscriptHandler(handler: ((text: string) => void) | null): void;
}
