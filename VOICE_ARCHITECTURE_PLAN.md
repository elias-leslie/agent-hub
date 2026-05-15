# Agent Hub voice architecture plan

## Scope and assumptions

- Goal: replace current push-to-talk-only stack with one approved voice plan for phone-first, wake-word-capable, low-latency interaction across Passport, chat, persona/Jenny, and related SummitFlow surfaces without building separate voice backends. Applied: [M:757618c5] [M:30f83ef3] [M:5138cf14]
- Assumption: this task asks for implementation plan, not code. No product behavior change in this diff. Applied: [M:f6943ad9]
- Constraint: Agent Hub remains canonical agent/session/memory/backend path. No parallel voice orchestration stack. Applied: [M:dc103a5e] [M:47c28223] [M:7ce57b1e]
- Constraint: use repo evidence for current state; use web only for external platform limits and option fit. Applied: [M:a20d9cc7] [M:046a6179]

## Current state from repo

### Existing client voice pieces

- Passport has hold-to-talk voice overlay UI in `packages/passport-client/src/components/VoiceOverlay.tsx:18`. Button uses `onMouseDown/onMouseUp` and `onTouchStart/onTouchEnd`; label says `Hold to speak`. No wake word, no follow-up loop, no interruption UX.
- Passport audio capture in `packages/passport-client/src/hooks/useVoice.ts:78` uses `getUserMedia`, `AudioContext({ sampleRate: 16000 })`, deprecated `createScriptProcessor(4096, 1, 1)`, base64-encodes PCM, sends WS messages `{type:"audio"}`. No VAD, no partial STT, no packet timestamps, no jitter handling, no background/mobile reliability features.
- Same hook fetches TTS from `/api/voice/tts` and plays decoded audio locally in `packages/passport-client/src/hooks/useVoice.ts:130`. Stop only kills current `AudioBufferSourceNode`; no coordinated barge-in cancel to backend.
- Passport also has browser STT fallback via Web Speech in `packages/passport-client/src/hooks/transcription/webSpeechEngine.ts:21`. It auto-restarts one phrase at a time because mobile Chrome behaves badly in continuous mode. Good evidence browser STT path already hit platform limits.
- Passport Whisper path in `packages/passport-client/src/hooks/transcription/whisperEngine.ts:16` is still push-to-talk over WS with full transcript only after stop. No streaming partials.
- Chat UI has keyboard/mic control helper in `packages/chat-ui/src/components/use-voice-input.ts:16`. It is push-to-talk/toggle logic only. No always-listening path.

### Existing backend voice pieces

- Agent Hub voice WS endpoint is `backend/app/api/endpoints/voice.py:230`. Query params: `user_id`, `app`, optional `session_id`, `mode`. WS loop receives text frames only.
- Backend stores raw audio in in-memory `audio_buffers` dict keyed by websocket id in `backend/app/api/endpoints/voice.py:103`. No durable stream/session object, no sequencing, no backpressure, no multi-turn audio state.
- On stop, backend writes temp WAV and runs STT in `_transcribe_audio` at `backend/app/api/endpoints/voice.py:117`, then optional completion in `_run_ai_completion` at `backend/app/api/endpoints/voice.py:131`. This is stop-and-process, not streaming.
- Current STT service in `backend/app/services/voice/stt.py:9` wraps `faster_whisper.WhisperModel` singleton with `transcribe()` over whole file. Defaults: `model_size="base"`, `device="cpu"`, `compute_type="int8"`. No streaming decoder, no VAD, no partial hypotheses, no diarization, no endpointing.
- Current TTS service in `backend/app/services/voice/tts.py:62` uses `edge_tts` and returns full MP3 bytes after synthesis. No streaming audio chunks, no low-latency first-byte path, no cancellation contract.
- Voice completion bypasses normal conversational session routing. `_run_ai_completion` in `backend/app/api/endpoints/voice.py:131` builds ad hoc system prompts from `VOICE_SYSTEM_PROMPTS` map and calls `complete_with_memory(... source=CompletionSource.VOICE, project_id=f"voice-{app}")`. That means voice today is not first-class on existing session graph, persona runtime, or shared prompt stack.

### Existing session/persona capabilities voice should reuse

- Persona has canonical voice preferences in `backend/app/models/persona.py:40-41` with `voice_id` and `voice_enabled`. Good source for TTS voice identity.
- Persona runtime in `frontend/src/app/persona/hooks/usePersonaRuntimeCore.ts:255` already tracks active persona/child sessions from shared `/api/sessions` and live session events. Voice should route into same session system, not side-channel.
- Shared session APIs already expose fetch/detail/cancel in `frontend/src/lib/api/sessions.ts:178`, `:212`, `:220`. `cancelSessionStream` posts to `/api/complete/cancel`. This is base for voice interruption/barge-in against running agent response.

## Exact architectural gaps

1. **No wake word path**
   - No repo code for hotword detection.
   - Browser overlay design is explicit hold-to-talk only.

2. **No reliable phone-first runtime**
   - Current clients are browser hooks/components.
   - Web Speech path already contains mobile workaround for phrase restart bug in Chrome in `packages/passport-client/src/hooks/transcription/webSpeechEngine.ts:48-51`.
   - No Android foreground-service or native audio session implementation in repo.

3. **No streaming STT/TTS**
   - STT waits for stop, writes WAV, then batch transcribes.
   - TTS returns full MP3 only after synth complete.
   - No partial transcript or partial audio events.

4. **No unified voice conversation protocol**
   - WS accepts raw audio/control blobs only.
   - No event schema for wake detected, VAD start/end, partial STT, agent turn start, TTS chunk, cancel ack, barge-in, follow-up timeout.

5. **Voice bypasses canonical session routing**
   - Ad hoc `VOICE_SYSTEM_PROMPTS` map in code and `project_id=f"voice-{app}"` path bypass shared agent prompt/session architecture. Conflicts with canonical context and agent routing direction. Applied: [M:d6f5ec92] [M:c4f0b1a1] [M:47c28223] [M:dc103a5e]

6. **No interruption model**
   - Client can stop local playback only.
   - No backend cancel of current TTS/STT/agent turn tied to user speech start.

7. **No follow-up turn window**
   - After one stop-and-respond cycle, system goes idle.
   - No “continue listening for 6 seconds” state or conversation timeout policy.

8. **No mobile/offline policy split**
   - No decision for what must run on device vs server.
   - No role assigned for Android app, Windows GPU box, Alexa endpoints.

## Platform facts that matter

- Android foreground services exist for user-noticeable ongoing work and show a status-bar notification. This fits always-listening/wake-word service better than browser tab assumptions. Source: Android docs fetched via `st web fetch` on foreground services. Applied: [M:046a6179]
- Porcupine markets Android/on-device/offline wake-word detection with always-on low-resource inference and SDKs for Android, React Native, Web, desktop. Good evidence on-device wake word is practical on Android and should not require server round-trips. Source: Picovoice Porcupine product page fetched via `st web fetch`. Applied: [M:046a6179]
- `faster-whisper` supports VAD filtering and is used by external streaming/live transcription projects, but core repo examples remain transcription-oriented, not a complete turnkey conversational realtime stack. Good fit for server STT core, but streaming policy and endpointing must be built around it. Source: `faster-whisper` repo fetched via `st web fetch`. Applied: [M:046a6179]
- Alexa wake word is device-owned. Custom skill path is not good control point for our own always-listening wake-word and low-latency barge-in stack. Use Alexa only as optional downstream surface, not primary architecture. Source: Alexa docs/web research plus industry behavior. Applied: [M:046a6179]

## Decision summary

### Approved target

**Primary architecture: native Android voice shell + Agent Hub voice runtime service + shared session/event contracts.**

- Wake word and local VAD on device.
- Streaming audio uplink to Agent Hub voice runtime.
- Agent Hub owns STT finalization, session routing, memory, persona, agent orchestration, and TTS generation.
- Shared packages define event schema and session/voice routing contracts.
- Browser surfaces keep push-to-talk fallback only. No promise of reliable wake word in browser.

Why this wins:

- Meets phone-first and wake-word reliability need.
- Reuses Agent Hub sessions/persona instead of parallel backend.
- Keeps privacy-sensitive continuous mic logic on device.
- Lets server own canonical transcript, context, routing, and observability.
- Can serve Passport, chat, persona/Jenny, SummitFlow from one backend voice runtime with surface-specific session metadata only.

## Alternatives considered

### Alternative A — browser-first wake word and voice web components

Shape:
- Extend current Passport/chat browser hooks.
- Do wake word, VAD, and audio in browser/PWA.

Pros:
- Lowest initial code churn.
- Reuses existing web packages fast.

Cons:
- Weak Android reliability for background/always-listening.
- Existing code already shows browser/mobile STT edge cases in Web Speech path.
- Browser permission/session lifecycle fights wake word, audio focus, and lock-screen behavior.
- Hard to guarantee low-latency resume and follow-up turns on phone.

Decision: **reject as primary path**. Keep only as fallback/manual push-to-talk path.

### Alternative B — GPU/Windows-box-first full voice sidecar

Shape:
- Put realtime STT/TTS/session loop on Windows 4080 box.
- Mobile app becomes thin audio pipe.

Pros:
- Best raw STT/TTS latency headroom.
- Easier to run larger realtime models.

Cons:
- High ops risk: uptime, auth, routing, deployment, observability.
- Tends to become parallel voice backend that bypasses Agent Hub sessions/persona.
- Harder to share cleanly across Passport/chat/Jenny without duplicating orchestration.

Decision: **reject as control plane**. Use Windows 4080 only as optional accelerator for STT/TTS workers behind Agent Hub service boundary.

### Alternative C — Alexa-centric voice front door

Shape:
- Alexa device handles wake word and user interaction; Agent Hub only skill backend.

Pros:
- Hardware exists now.
- Good far-field capture for home use.

Cons:
- Not phone-first.
- Alexa owns wake word and UX envelope.
- Weak fit for Passport/chat embedded surfaces.
- Hard to align with persona/session continuity and barge-in semantics we control.

Decision: **reject as primary surface**. Keep as later integration surface if needed.

## Explicit device role decisions

### Dedicated Android app

**Yes. Required.**

Role:
- Primary phone-first client for wake word, background audio session, local VAD hints, push-to-talk fallback, audio playback, and interruption UX.
- Single mobile shell can host Passport/chat/persona entry points via auth + surface metadata, not separate voice apps.

Reason:
- Browser path cannot safely own reliable wake word/background voice on Android.
- Native app can run foreground service, manage audio focus, Bluetooth, lock screen, notification, and reconnection.

### Windows 4080 box

**Yes, but as optional acceleration tier only. Not authority.**

Role:
- Host GPU-backed STT/TTS workers if latency testing proves CPU path misses targets.
- Exposed behind Agent Hub voice runtime as provider endpoint; never direct client dependency.

Reason:
- Good latency lever for faster-whisper or better TTS, but should not create second session/orchestration plane.

### Alexa devices

**No as core architecture. Maybe later as adapter surface.**

Role:
- Optional integration surface for home/ambient use after Android path stable.
- Alexa handles its own wake word; Agent Hub receives intent/audio turn through integration adapter only.

Reason:
- Does not satisfy phone-first requirement.
- Too much UX/control delegated to Alexa platform.

## Target end-to-end design

### 1. Wake word

Primary:
- Android app runs on-device wake word engine in foreground service.
- Use one branded wake phrase plus optional short alias.
- Wake detector muted while TTS audio playing unless headset/private mode explicitly allows full duplex experimentation.

Fallback:
- Manual tap/hold mic in app and browser.

Not in scope for phase 1:
- Browser wake word guarantee.
- Alexa custom wake word.

### 2. VAD and endpointing

On device:
- Local VAD opens upstream audio stream only after wake or manual press.
- Client sends `speech_started`, `speech_ended`, RMS level, and optional local timestamps as hints.

Server:
- Agent Hub voice runtime performs canonical endpointing and transcript commit.
- Server VAD/endpointer decides final utterance boundary for session turn.
- Client hints can speed UX but do not become source of truth.

Reason:
- Client VAD cuts latency/bandwidth.
- Server endpointing keeps one consistent transcript/session record across clients.

### 3. STT

- Stream PCM frames from Android to Agent Hub over voice WS/SSE-realtime channel.
- Voice runtime feeds streaming STT worker.
- Emit partial transcript events for live captions.
- Commit final transcript when server endpointer closes utterance.
- Store final transcript in canonical Agent Hub session turn.

Implementation preference:
- Keep faster-whisper family first because repo already uses it in `backend/app/services/voice/stt.py:9`.
- Upgrade from file-batch path to streaming wrapper with VAD-aware chunking.
- If CPU latency misses target, move worker to 4080 box behind same provider interface.

### 4. Agent/session routing

- Every voice turn must attach to normal Agent Hub session id.
- Client starts/resumes session for one of: Passport, chat, persona/Jenny, SummitFlow surface.
- Voice runtime passes transcript into same session engine used by text chat.
- Surface-specific behavior comes from `agent_slug`, persona settings, and session metadata, not separate voice prompt maps.
- Delete/retire ad hoc `VOICE_SYSTEM_PROMPTS` design after migration.

Routing model:
- `surface=passport|chat|persona|summitflow`
- `agent_slug` explicit or inferred from surface
- `session_id` required after first turn
- persona voice prefs loaded from canonical persona row when applicable

### 5. TTS

- Agent Hub generates response text first through normal session engine.
- TTS service synthesizes audio for committed assistant turn using persona/surface voice selection.
- Stream audio chunks to client as produced when provider supports it; otherwise chunk buffered MP3/PCM from provider wrapper.
- Client starts playback on first playable chunk, not full file completion.

Voice source priority:
1. explicit session/surface override
2. persona `voice_id` when persona surface
3. default app voice

### 6. Interruption / barge-in

- If user starts speaking during TTS playback, client immediately ducks/stops local audio and sends `barge_in` event.
- Agent Hub cancels active TTS stream and, if agent generation still active, calls shared session cancel path equivalent to `cancelSessionStream` in `frontend/src/lib/api/sessions.ts:220`.
- New speech starts new user turn on same session.
- Transcript and event log record interruption for analytics/debug.

Need:
- Voice runtime and shared session engine must distinguish cancel-generation vs stop-audio-only.

### 7. Follow-up turns

State machine:
- `idle`
- `armed` after wake word
- `listening`
- `thinking`
- `speaking`
- `followup_wait`

Policy:
- After assistant speech ends, client enters short follow-up window, example 4–8s.
- During window, no wake word required; simple VAD speech start reopens turn on same session.
- Timeout returns to `armed` if hands-free mode enabled, else `idle`.
- User can pin conversation active mode for longer session.

### 8. Error handling and offline behavior

- If network drops during turn, client announces short local earcon/text state and retries session reconnect once.
- If server unavailable, app falls back to push-to-talk local note only if explicitly designed later; not phase 1 default.
- Wake word remains local even when backend down; post-wake response tells user service unavailable.

## Ownership by layer

### Agent Hub backend

Own:
- Canonical voice session service bound to existing session ids
- streaming STT orchestration and transcript commit
- canonical VAD/endpointer decision
- agent routing through existing session/persona stack
- TTS provider abstraction and stream output
- cancel/barge-in semantics tied to existing session cancelation
- voice event logging, metrics, latency traces, failure diagnostics
- auth and surface authorization for voice sessions

Must change:
- Replace ad hoc `backend/app/api/endpoints/voice.py` stop-and-batch design with realtime voice runtime API.
- Remove code-owned `VOICE_SYSTEM_PROMPTS` and route via DB prompts/session agent path. Applied: [M:d6f5ec92] [M:c4f0b1a1]

### Shared packages

Own:
- cross-surface voice event schema
- typed client protocol for `session_started`, `audio_frame`, `speech_started`, `partial_transcript`, `final_transcript`, `assistant_response_start`, `tts_chunk`, `tts_end`, `barge_in`, `error`
- shared session routing helpers
- shared persona voice preference resolution types
- shared UX state machine definitions if reused by web/mobile

Candidates:
- `packages/chat-ui` for generic voice state hooks only if truly cross-surface
- new small shared package for protocol/types if cleaner

### Mobile client

Own:
- Android foreground service
- wake word engine integration
- local VAD/audio capture/audio focus/Bluetooth/headset
- mic permission UX
- local playback and ducking
- reconnect strategy
- follow-up timer UX
- manual controls and surface switcher

Should not own:
- prompt logic
- session orchestration semantics
- transcript truth
- TTS voice policy beyond rendering server-selected stream

### Browser clients

Own:
- fallback push-to-talk only
- optional live transcript display and playback using same backend protocol where possible

Should not own:
- guaranteed wake word/background voice promises

## Recommended technical shape

### Voice protocol

Use one canonical realtime voice protocol under Agent Hub. Example events:

Client -> server:
- `session.open`
- `audio.start`
- `audio.frame`
- `audio.stop`
- `vad.start`
- `vad.end`
- `barge_in`
- `ping`

Server -> client:
- `session.ready`
- `stt.partial`
- `stt.final`
- `agent.turn_started`
- `agent.text_delta` optional
- `agent.turn_committed`
- `tts.start`
- `tts.chunk`
- `tts.end`
- `turn.cancelled`
- `error`

Transport:
- Start with WebSocket binary frames for audio + JSON control envelopes.
- Keep auth/session semantics aligned with existing Agent Hub clients and session ids.

### Session model

- Voice is modality on existing session, not new entity.
- Add modality metadata and voice event timeline rows if needed.
- Final user and assistant messages remain normal session messages.
- Partial STT/TTS artifacts can be ephemeral or stored as session events, not canonical messages.

### STT/TTS provider abstraction

- Keep single Agent Hub provider shape. Do not build separate voice orchestration plane. Applied: [M:946d457d] [M:dc103a5e]
- Add voice worker interface with pluggable implementations:
  - local CPU faster-whisper
  - remote GPU worker on 4080
  - current edge-tts or better streaming TTS provider

## Implementation phases

### Phase 0 — architecture approval

Deliver:
- Approve this plan.
- Confirm Android app is greenlit.
- Confirm 4080 box role = optional accelerator, not authority.
- Confirm Alexa = later adapter only.

Proof:
- Stakeholder sign-off doc with chosen path and rejected alternatives.

### Phase 1 — canonical backend voice protocol

Build:
- New Agent Hub voice session protocol and endpoint.
- Bind voice turns to existing session ids.
- Replace ad hoc voice prompt map with normal session/agent routing.
- Add session cancel/barge-in path for voice.
- Emit partial/final STT + TTS stream events.

Proof:
- CLI or test client can stream audio and receive partial transcript + assistant text + TTS chunks on one session.
- Session detail API shows final messages in same session.
- Interruption cancels current turn cleanly.

Verification:
- focused backend tests for protocol, routing, cancelation
- `st check --check` pass before merge

### Phase 2 — streaming STT and streaming TTS core

Build:
- Streaming wrapper around faster-whisper-based STT with server endpointing.
- TTS chunk streaming contract.
- latency instrumentation: wake-to-first-partial, end-of-speech-to-first-token, first-token-to-first-audio, barge-in cancel time.

Proof:
- Measured local test latency on CPU baseline.
- If target missed, same tests against 4080 worker path.

Verification:
- synthetic audio fixture tests
- soak test with repeated turns
- `st check --check`

### Phase 3 — Android app MVP

Build:
- Native Android app with auth
- foreground voice service
- push-to-talk + streaming voice session
- TTS playback + barge-in
- session resume across Passport/chat/persona surfaces

Proof:
- screen-off, headset, Bluetooth, lock-screen manual voice works on Android device.
- same backend session visible in Agent Hub/SummitFlow UI.

Verification:
- device test matrix
- network drop/reconnect checks
- battery and notification sanity

### Phase 4 — wake word and follow-up loop

Build:
- on-device wake word
- local VAD hints
- follow-up window state machine
- hands-free mode controls

Proof:
- wake phrase triggers from idle with screen off.
- follow-up second turn works without repeat wake word.
- false wake and missed wake measured in noisy room sample.

Verification:
- controlled wake-word benchmark set
- barge-in during TTS repeated trials

### Phase 5 — web fallback and surface adoption

Build:
- browser clients use same backend protocol for push-to-talk where useful
- Passport/chat/persona UI adoption through shared components and session metadata

Proof:
- one backend voice runtime serves all surfaces with no duplicate prompt/session logic.

Verification:
- per-surface smoke tests
- session trace review

### Phase 6 — optional 4080 acceleration and Alexa adapter

Build only if needed:
- GPU-backed STT/TTS workers behind Agent Hub abstraction
- optional Alexa adapter mapping Alexa requests into same session/voice backend where feasible

Proof:
- latency gain justifies complexity
- no client depends directly on 4080 host

## Milestones and exit criteria

1. **M1 Protocol alive** — realtime endpoint, session binding, partial STT, final messages persisted
2. **M2 Interrupt works** — barge-in stops playback and cancels backend turn reliably
3. **M3 Android manual voice works** — phone-first push-to-talk reliable in foreground/background service
4. **M4 Wake word works** — on-device activation and follow-up loop stable
5. **M5 Surface convergence** — Passport/chat/persona all use same backend voice runtime
6. **M6 Optional acceleration** — 4080 path only if measured need

## Proof and verification plan

For each phase capture:
- exact test command(s)
- latency numbers
- failure rate from repeated-turn runs
- session trace screenshots/logs
- battery/CPU sample on Android for always-listening mode

Minimum acceptance metrics to define before build starts:
- wake-to-listening indicator target
- end-of-speech-to-first-text target
- end-of-speech-to-first-audio target
- barge-in stop target
- false accept / false reject wake-word thresholds
- reconnect success rate target

## Open questions for stakeholder review

1. Android app scope: standalone app, SummitFlow shell app, or embeddable wrapper around existing web surfaces?
2. Auth model for mobile background service: existing SummitFlow auth enough, or need device token/session refresh path?
3. Latency target numbers: what counts as acceptable for “low latency” on Wi‑Fi vs mobile network?
4. TTS provider: is current `edge_tts` quality/latency acceptable, or should provider upgrade happen early?
5. Wake word branding: single shared wake phrase or persona/surface-specific variants?
6. Privacy posture: must raw audio ever be stored, or only ephemeral buffered frames plus final transcript?
7. 4080 uptime: who operates and monitors it if phase 6 used?
8. Alexa scope: read-only persona/chat access, or full session continuation?
9. Should browser surfaces expose same follow-up loop when tab active, or stay manual only?
10. Do we need duplex agent speech + user interruption in headset mode, or half-duplex first?

## Main risks

- **Architecture drift to sidecar**: GPU worker can quietly become parallel backend. Prevent by forcing all paths through Agent Hub session/runtime boundary.
- **Browser temptation**: easier short-term, fails phone-first reliability requirement.
- **Wake-word false alarms**: need measured tuning and opt-in hands-free mode.
- **TTS latency**: current full-MP3 `edge_tts` path may feel slow; may force provider or streaming wrapper work earlier than planned.
- **Backend complexity**: realtime protocol, cancelation, and session/event integration touch core surfaces. Keep one protocol, one session path.
- **Mobile ops**: Android foreground-service UX and battery cost need early real-device validation.

## Final recommendation

Approve **native Android client + Agent Hub canonical voice runtime**.

Do not approve browser-first wake word as primary plan.
Do not approve Windows 4080 as separate voice brain.
Do not approve Alexa as primary control surface.

This path gives reliable wake word, phone-first UX, low-latency route, and keeps Passport/chat/Jenny/persona on one Agent Hub session and persona architecture instead of spawning parallel voice stack.
