/**
 * Voice for `@agent-hub/chat-ui`, kept out of the main entry so a host without `@agent-hub/passport-client` can
 * use the chat. Install passport-client and import from `@agent-hub/chat-ui/voice` to add a mic and speaker.
 */
export { useChatVoice } from './voice/use-chat-voice';
export type { UseChatVoiceOptions } from './voice/use-chat-voice';
export { useVoicePreferences, createHttpPreferencesStore } from './voice/use-voice-preferences';
export type { VoiceOption, VoicePreferences, VoicePreferencesStore } from './voice/use-voice-preferences';
export type { ChatVoice } from './types/voice';
