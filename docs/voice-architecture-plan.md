# Agent Hub voice architecture plan

Status: proposed implementation plan

## Scope and assumptions
- Goal: reliable wake-word, low-latency, phone-first voice across Passport, chat, Jenny/persona, and SummitFlow surfaces.
- Constraint: no parallel voice brain. Agent Hub remains canonical session, agent routing, persona, memory, and TTS/STT service layer. Applied: [M:dc103a5e] [M:7ce57b1e] [M:47c28223]
- Simpler path exists: keep browser push-to-talk for desktop fallback, but move always-listening phone UX to dedicated Android client. Browser cannot be primary for wake-word/background reliability on Android.
- Assumption: this task asks for plan, not code rollout.

## Current stack in repo

### Agent Hub backend today
- `/api/voice/ws` buffers raw PCM chunks in memory per websocket, writes temp WAV on stop, then runs one-shot faster-whisper transcription. No partials, no VAD, no wake-word, no barge-in state machine. `backend/app/api/endpoints/voice.py:103-245`
- Voice websocket has only two meaningful control actions: `start` and `stop`. `backend/app/api/endpoints/voice.py:27-33`, `backend/app/api/endpoints/voice.py:217-223`
- Assistant mode runs `_run_ai_completion()` with ad hoc system prompt map by `app`, `project_id=f"voice-{app}"`, and `memory_group_id=user_id`. It does not route through canonical product session/thread semantics for Passport/chat/persona. `backend/app/api/endpoints/voice.py:131-162`
- `_resolve_voice_agent()` already resolves a `voice-responder` agent via routing context `requires_audio=True`. Good seed for canonical routing. `backend/app/api/endpoints/voice.py:250-268`
- STT service is local `faster_whisper.WhisperModel`, lazy-loaded, one-shot `transcribe()`, default `base` on CPU/int8. No streaming decoder path, no VAD config, no partial transcript API. `backend/app/services/voice/stt.py:9-51`
- TTS service uses `edge_tts`, returns full MP3 bytes after synthesis. No stream chunks, no cancel, no resume markers, no timing metadata. `backend/app/services/voice/tts.py:62-85`
- Connection manager only tracks websockets by user/session and sends JSON messages. No duplex audio control plane, no interrupt command fanout, no per-turn state. `backend/app/services/voice/connection_manager.py:20-64`

### Passport client today
- `VoiceOverlay` is hold-to-talk UI. `packages/passport-client/src/components/VoiceOverlay.tsx:18-112`
- `useVoice()` opens websocket, captures mic with `ScriptProcessorNode`, base64-encodes PCM, sends `start/stop`, fetches `/api/voice/tts`, then plays decoded audio locally. No wake-word, no VAD, no echo cancel loop, no interruption protocol, no follow-up timer. `packages/passport-client/src/hooks/useVoice.ts:12-195`
- `useWhisperEngine()` is same pattern for transcript-only mode. Stop triggers server batch transcription. No streaming partials. `packages/passport-client/src/hooks/transcription/whisperEngine.ts:16-133`

### Chat and persona UI today
- Persona footer wires `MessageInput` to `/api/voice/ws?...mode=transcribe`. Transcript becomes plain chat send. `frontend/src/app/persona/components/WorkspaceChatFooter.tsx:100-111`
- Main chat panel also wires voice as transcript-only input to same websocket. `frontend/src/components/chat/chat-panel.tsx:154-207`
- `useMessageInput()` sends transcript text into normal message flow, then normal SSE/text completion happens separately. Good sign: text/session stack already canonical after transcript lands. `packages/chat-ui/src/components/use-message-input.ts:79-115`
- Response speaking is bolt-on: when text stream finishes and TTS enabled, client fetches full `/api/voice/tts` MP3 and plays it. `packages/chat-ui/src/components/chat-panel.tsx:129-152`
- `useVoiceInput()` is spacebar or mic click push-to-talk only. `packages/chat-ui/src/components/use-voice-input.ts:16-100`

## Exact architectural gaps
1. No wake word anywhere.
2. No always-listening/background-safe mobile client.
3. No VAD-driven turn detection; only manual press/release.
4. No streaming STT partials; transcript appears only after stop.
5. No canonical voice session protocol shared across Passport/chat/persona.
6. No real interruption/barge-in path. Client can stop local playback, but not cancel live LLM/TTS turn end-to-end. `packages/passport-client/src/hooks/useVoice.ts:176-183`, `frontend/src/lib/api/sessions.ts:220-232`
7. No follow-up turn window or open-mic state machine.
8. No transport for TTS audio chunks; only full-file fetch.
9. Voice completion path partly bypasses product session identity with `project_id=f"voice-{app}"`. `backend/app/api/endpoints/voice.py:146`
10. Browser audio capture path uses deprecated `ScriptProcessorNode`, base64 overhead, and playback through same `AudioContext`; not ideal for low latency. `packages/passport-client/src/hooks/useVoice.ts:25`, `packages/passport-client/src/hooks/useVoice.ts:87-109`
11. Persona voice enable flag gates TTS, but voice policy/config is not yet first-class cross-surface voice session config. `backend/app/api/endpoints/voice.py:80-99`, `backend/app/models/persona.py:53-55`

## Viable target options

### Option A — Browser-first evolution
Keep web app as primary client. Add JS wake-word, VAD, streaming STT, and barge-in in browser.

Pros
- Least new app work.
- Reuses current chat-ui and Passport components.

Cons
- Fails phone-first/background reliability goal on Android due to browser suspension, mic permission friction, and inconsistent wake-word/background behavior.
- Harder audio focus, lock-screen, headset, Bluetooth, notification, foreground service handling.
- Weakest path for always-on Jenny/persona use.

Decision
- Reject as primary architecture.
- Keep only as fallback push-to-talk web mode.

### Option B — Dedicated Android client, Agent Hub canonical backend, optional GPU STT accelerator
Android app owns wake-word, VAD, audio focus, and playback UX. Agent Hub owns voice session protocol, routing, session continuity, memory, persona identity, and TTS/STT orchestration. Windows 4080 box may host accelerated STT/TTS workers behind Agent Hub service contracts, not as a separate product stack.

Pros
- Best fit for reliable phone-first wake-word and background behavior.
- Preserves single Agent Hub session/agent architecture.
- Lets GPU box improve latency without changing client contract.
- Browser/web can reuse same backend voice session API in push-to-talk mode.

Cons
- New Android app work.
- Need mobile auth/device session design.
- Need more backend protocol work than current websocket.

Decision
- Select this option.

### Option C — Alexa-first or Alexa-equal architecture
Use Alexa devices as main wake-word front end and route to Agent Hub.

Pros
- Hardware already has mic/speaker/wake-word solved.

Cons
- Alexa wake word is device-native, not product-controlled; custom skills do not make Agent Hub own the wake word.
- Alexa interaction model constrains continuous low-latency open conversation and custom interruption behavior.
- Weak fit for Passport/chat/persona shared UX and session continuity.

Decision
- Reject as primary architecture.
- Keep only as optional secondary surface later.

## External facts that shape decisions
- Porcupine markets on-device wake-word for Android and edge/offline use. Good fit for local wake-word trigger in dedicated mobile app. Source: `st web fetch` on Picovoice Porcupine. Applied: [M:046a6179]
- `faster-whisper` supports VAD filtering and efficient transcription, but repo/documentation is still transcription-centric, not a drop-in full duplex voice session stack. Need our own session protocol and streaming orchestration. Source: `st web fetch` on SYSTRAN/faster-whisper. Applied: [M:046a6179]
- Alexa skills are official extension path, but custom skills ride Alexa device constraints instead of owning custom always-listening behavior. Source: `st web fetch` on Amazon Alexa Skills Kit page. Applied: [M:046a6179]

## Chosen target architecture

### Core rule
One voice architecture only:
- Client captures audio and renders audio UX.
- Agent Hub owns voice session state, agent/session routing, persona mapping, memory continuity, interrupt semantics, and speech service selection.
- Optional accelerators sit behind Agent Hub as workers/adapters, never peer product stacks. Applied: [M:dc103a5e] [M:7ce57b1e] [M:47c28223]

### Dedicated Android app
Decision
- Yes. Required for primary phone experience.

Role
- Foreground service for always-ready listening mode.
- On-device wake-word detection.
- On-device VAD front gate.
- Audio focus, headset/Bluetooth handling, notification controls.
- Playback with immediate stop on barge-in.
- Device auth and reconnect logic.

Why
- Needed for reliable wake-word/background behavior. Browser-first cannot meet this cleanly.

### Windows 4080 box
Decision
- Yes, but only as optional speech accelerator pool behind Agent Hub.

Role
- Host low-latency STT worker for streaming partials and finals.
- Optionally host faster/voice-cloned TTS later if needed.
- Never own user sessions, auth, persona logic, or routing.

Why
- Good latency/cost lever. Bad source of truth.

### Alexa devices
Decision
- Not core architecture.
- Support later only as a narrow bridge surface if stakeholders want room voice access.

Role if added later
- Alexa skill sends utterance/events into Agent Hub voice session API.
- No attempt to make Alexa the canonical wake-word or session runtime.

Why
- Device constraints and product mismatch.

## End-to-end flow

### 1. Idle and wake word
Primary Android mode:
1. Android foreground service holds low-power audio loop.
2. On-device wake-word engine detects chosen trigger locally.
3. On wake, app plays short earcon, starts voice session if absent, opens duplex websocket/WebRTC-like stream to Agent Hub voice gateway.
4. App enters `listening_for_command` state.

Fallback web mode:
- No wake word. Manual push-to-talk only.

### 2. VAD and turn capture
1. Android runs local VAD to decide speech start/end fast.
2. App streams framed PCM/opus audio upstream from speech start.
3. Agent Hub also runs server VAD/turn finalization as guard against client errors.
4. End-of-turn fires on trailing silence or explicit user stop.

Reason for dual VAD
- Client VAD cuts latency.
- Server VAD gives canonical transcript boundaries and protects bad devices.

### 3. STT
1. Agent Hub voice gateway receives audio frames.
2. Voice gateway forwards frames to STT worker via internal async stream.
3. STT worker emits partial transcripts and final transcript.
4. Agent Hub persists voice turn events onto canonical session/thread.

Decision
- Use streaming STT worker contract, not current temp-WAV batch path.
- Keep faster-whisper family first. Run on 4080 worker for phone-primary low latency. CPU fallback remains for degraded service.

### 4. Agent/session routing
1. Client passes target surface metadata: `surface=passport|chat|persona|summitflow`, `agent_slug`, `session_id`, `thread_id`, `persona_id`, `project_id`, optional `external_id`.
2. Agent Hub maps voice turn into existing canonical session system, same as text chat.
3. Transcript is inserted as normal user message into the target session.
4. Existing Agent Hub agent routing chooses model/agent. Applied: [M:7ce57b1e] [M:cf55594f]
5. Voice-specific behavior lives as presentation/session mode flags, not separate agent architecture.

Important correction to current stack
- Remove ad hoc `project_id=f"voice-{app}"` path for product conversations. Voice should attach to real product session/project. `backend/app/api/endpoints/voice.py:146`

### 5. Response generation
1. Once transcript finalizes, Agent Hub starts normal streamed completion on canonical session.
2. Voice gateway emits text partials plus response-state events.
3. TTS can start once sentence chunk or stable token chunk forms.

Decision
- Do not wait for full response before TTS in phone mode.
- Keep full-response TTS fetch only for legacy web fallback.

### 6. TTS
1. Agent Hub text stream feeds TTS chunker.
2. TTS worker returns audio chunks plus segment markers.
3. Client plays chunks immediately.
4. Persona voice selection remains source for default voice. `backend/app/models/persona.py:53-55`

Decision
- TTS stays backend-owned.
- Client never picks a separate speech stack beyond playback.

### 7. Interruption / barge-in
1. While TTS playing, Android VAD keeps monitoring mic at low level or resumes hot mic per mode.
2. If user starts speaking, client stops local playback instantly.
3. Client sends `interrupt` event to Agent Hub voice session.
4. Agent Hub cancels active LLM stream on canonical session and aborts TTS worker stream.
5. New user audio continues into same session as next turn.

Needed backend link
- Reuse canonical session cancel endpoint semantics under live voice session control plane. Current plain chat already has cancel API. `frontend/src/lib/api/sessions.ts:220-232`

### 8. Follow-up turns
1. After TTS ends, session enters short `follow_up_window` state, ex. 4-8s configurable.
2. During window, no wake word needed; VAD alone can open next turn.
3. If timeout expires, app returns to wake-word idle.
4. Explicit conversation mode can pin open session longer for task-heavy chat.

Why
- Feels conversational without always-hot endless mic.

## Component ownership

### Agent Hub backend
Must own
- Voice session API and protocol.
- Voice session state machine.
- Mapping voice turns to canonical Agent Hub sessions.
- AuthN/AuthZ for device/client voice sessions.
- STT/TTS provider abstraction and worker selection.
- Interrupt, cancel, and follow-up logic.
- Persona voice defaults and per-surface routing.
- Metrics: latency, turn timings, wake success, false wake, interrupt success, STT final WER proxies, reconnects.

Should add
- `VoiceSession` model or equivalent event/state layer tied to existing `Session`.
- New duplex stream endpoint for framed audio/events.
- Shared voice event schema.
- Streaming TTS pipeline.
- Streaming STT adapter contract.

### Shared packages
Belong here
- TS/py voice event schema types.
- Session-routing payload types.
- Shared client SDK helpers for voice session create/resume/cancel.
- Web push-to-talk client using same protocol in degraded mode.

Should not live here
- Android wake-word engine glue.
- Native audio capture details.

### Mobile client
Must own
- Wake-word engine integration.
- Local VAD.
- Audio device handling.
- Foreground service and notifications.
- Playback queue and instant local stop.
- Reconnect/resume UX.
- Mic/privacy indicators and settings.

## Recommended protocol shape
Single canonical voice protocol. Example event families:
- client -> server: `session.start`, `audio.append`, `audio.commit`, `interrupt`, `turn.cancel`, `session.resume`, `session.end`, `playback.mark`
- server -> client: `session.ready`, `vad.start`, `stt.partial`, `stt.final`, `turn.accepted`, `llm.partial`, `tts.segment`, `tts.audio`, `turn.done`, `error`

Transport decision
- Phase 1: websocket binary/audio frames plus JSON control. Smallest diff from today.
- Later only if needed: WebRTC for jitter/network gains. Do not front-load. Applied: [M:1fab9af9] [M:5138cf14]

## Implementation phases

### Phase 0 — approval and measurement
Deliverables
- Approve Option B and component boundaries.
- Define latency SLOs: wake-to-earcon, speech-end-to-transcript-final, transcript-final-to-first-audio, interrupt-to-silence.
- Inventory auth path for mobile client.

Proof
- Stakeholder signoff on this plan.
- Baseline current voice timings from existing push-to-talk stack.

### Phase 1 — canonical backend voice session layer
Build
- New voice session state machine in Agent Hub backend.
- Event schema in shared package.
- Tie voice sessions to real `Session` IDs and `agent_slug` routing.
- Interrupt command mapped to stream cancel.
- Metrics and structured logs.

Proof
- Simulated client test proves: partial STT event flow, final transcript insertion into session, cancel path, follow-up timer state.
- `st check` passes for touched packages. Applied: [M:ef2158aa] [M:c918f298]

### Phase 2 — streaming STT service
Build
- Replace temp-WAV batch path with streaming STT adapter.
- CPU fallback adapter in Agent Hub host.
- 4080-backed adapter worker for fast path.
- Server VAD guard.

Proof
- Bench test on sample audio: partials under target budget, finals stable, fallback works with accelerator disabled.
- Compare latency against current one-shot path.

### Phase 3 — streaming TTS plus interruption
Build
- Streaming TTS chunks from backend.
- Client playback queue semantics.
- End-to-end barge-in: playback stop, server cancel, next-turn capture.

Proof
- Automated integration test: playback started, interrupt event sent, server stream canceled, new turn accepted in same session.

### Phase 4 — Android app MVP
Build
- Authenticated Android client.
- Wake-word, VAD, duplex voice session, playback, follow-up window.
- Surface routing choices: Passport, chat, Jenny/persona.

Proof
- Field test on locked-screen/background Android device.
- Measure false wake rate, reconnect behavior, battery impact, headset path.

### Phase 5 — web fallback migration
Build
- Update Passport/chat web push-to-talk clients to use canonical voice session protocol.
- Keep no-wake-word manual mode.
- Remove old `/api/voice/ws` semantics after parity.

Proof
- Existing web voice still works through new backend path.

### Phase 6 — optional Alexa bridge
Build only if approved
- Narrow skill bridge into Agent Hub voice/text session API.

Proof
- Separate pilot. Not blocker for core rollout.

## Milestones
1. Architecture approved.
2. Canonical backend voice session API merged.
3. Streaming STT on CPU fallback merged.
4. 4080 accelerator live behind backend abstraction.
5. Streaming TTS + barge-in merged.
6. Android MVP handles Jenny/persona end to end.
7. Passport/chat web fallback migrated.

## Verification plan
- Unit: voice state transitions, interrupt semantics, follow-up timeout, persona voice defaults.
- Integration: duplex session with partial STT, final transcript, streamed LLM, streamed TTS, cancel, resume.
- Device: Android foreground/background, screen-off wake, Bluetooth headset, network drop/reconnect.
- Load: concurrent voice sessions across CPU fallback and 4080 worker.
- Product: same session visible in existing Agent Hub/SummitFlow session views.

## Open questions
1. Mobile auth: reuse current dashboard/client auth headers or mint device-scoped tokens?
2. Wake phrase ownership: one global Jenny phrase or per-surface phrases?
3. Privacy policy for always-listening foreground service and local-only pre-wake buffering.
4. STT engine choice on 4080: stay faster-whisper family or use dedicated realtime engine if latency misses SLO?
5. TTS provider: edge-tts may be enough first; if not, what streaming-capable replacement fits persona voices?
6. Need bilingual or multilingual wake/STT from day one?
7. Session UX: when should voice start a new thread versus continue current thread?

## Main risks
- Android app auth/reconnect complexity.
- GPU worker uptime becoming hidden SPOF if no CPU fallback.
- Premature WebRTC complexity.
- Letting voice shortcut existing Agent Hub session model again.
- TTS provider may block true low-latency chunking.

## Explicit decisions summary
- Primary architecture: dedicated Android app + Agent Hub canonical voice backend.
- Browser-first: fallback only.
- Windows 4080: yes, accelerator only, not source of truth.
- Alexa: optional later bridge, not core path.
- Wake word: on-device Android.
- VAD: client primary, server guard.
- STT: streaming behind Agent Hub; current batch temp-WAV path retired.
- Routing: canonical Agent Hub sessions and `agent_slug`, not ad hoc voice projects.
- TTS: backend-owned, streamed for phone mode.
- Barge-in: first-class end-to-end cancel path.
