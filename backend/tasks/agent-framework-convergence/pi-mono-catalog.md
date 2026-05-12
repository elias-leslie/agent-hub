# pi-mono AI Adapter Package — Reference Catalog

**Reference baseline for the convergence refactor.** Generated as Phase 0.2 of task `task-e65e9ee0`.

- **Source repo:** `badlogic/pi-mono` (cloned at `~/references/pi-mono`)
- **Tip SHA:** `3d9e14d7482f4a99d5224926099bec0d17ff86fd` ("fix(compaction): clamp summary output tokens")
- **Scope:** `packages/ai/src/` (the universal AI adapter package)
- **Verified up-to-date:** `git fetch origin && git pull --ff-only origin main` — already at tip.

> This document is the immutable reference baseline. Future sessions diff against it without re-deriving. Any divergence in the agent-hub port from what is documented here MUST be justified in `convergence-map.md`.

---

## 1. Top-level layout

### `packages/ai/src/` — 50 .ts files, 30,616 LOC total

```
src/
├── api-registry.ts                     98L   — universal ApiProvider interface + registry
├── bedrock-provider.ts                  6L   — bedrock provider re-export shim
├── cli.ts                             133L   — pi CLI entrypoint (out of refactor scope)
├── env-api-keys.ts                    210L   — per-provider env var resolution
├── image-models.generated.ts          264L   — image-model registry (out of scope)
├── image-models.ts                     42L   — image-model lookup (out of scope)
├── images-api-registry.ts              53L   — image ApiProvider registry (out of scope)
├── images.ts                           21L   — images entry surface (out of scope)
├── index.ts                            46L   — public barrel
├── models.generated.ts             17,252L   — generated per-provider model registry
├── models.ts                           92L   — model lookup + cost calc + thinking helpers
├── oauth.ts                             1L   — re-export `utils/oauth/index.ts`
├── session-resources.ts                24L   — minor session helper (compaction)
├── stream.ts                           59L   — `stream`/`streamSimple`/`complete`/`completeSimple` thin wrappers
├── types.ts                           565L   — universal types (Message/Tool/Usage/etc.)
├── providers/                        9,086L  — per-provider implementations
└── utils/                              805L  — utilities (+ utils/oauth subtree)
```

### `src/providers/` — 17 files, 9,086 LOC

```
providers/
├── amazon-bedrock.ts                  956L
├── anthropic.ts                     1,207L   — reference depth (deepest provider)
├── azure-openai-responses.ts          281L
├── cloudflare.ts                       35L   — URL/detection helper only (no full provider)
├── faux.ts                            499L   — test double
├── github-copilot-headers.ts           37L   — header helper used by anthropic.ts + openai-completions.ts
├── google-shared.ts                   350L   — shared by google.ts + google-vertex.ts
├── google.ts                          501L
├── google-vertex.ts                   568L
├── mistral.ts                         634L
├── openai-codex-responses.ts        1,351L   — WebSocket + HTTP transports (largest)
├── openai-completions.ts            1,148L
├── openai-responses.ts                295L
├── openai-responses-shared.ts         551L   — shared by openai-responses + azure-openai-responses + openai-codex-responses
├── register-builtins.ts               403L   — lazy-loading registration of the 9 built-in APIs
├── simple-options.ts                   50L   — reasoning-level → provider mapping helpers
├── transform-messages.ts              220L   — universal Message[] normalization (cross-provider)
└── images/                             237L  — out of scope
```

**Tight-shared-helper precedents** (justifying any "second file" in a port):
- `google-shared.ts` is shared by `google.ts` + `google-vertex.ts`
- `openai-responses-shared.ts` is shared by `openai-responses.ts` + `azure-openai-responses.ts` + `openai-codex-responses.ts`
- `transform-messages.ts` is shared across `anthropic.ts`, `openai-completions.ts`, `amazon-bedrock.ts`, `mistral.ts`
- `simple-options.ts` is shared across all providers (reasoning options)
- `github-copilot-headers.ts` is shared across `anthropic.ts` + `openai-completions.ts`
- `cloudflare.ts` is just a URL helper — NOT a provider; AI Gateway is consumed via base-URL routing in other providers

### `src/utils/` — 9 files, 805 LOC

```
utils/
├── diagnostics.ts             45L   — error info + diagnostic event helpers
├── event-stream.ts            87L   — EventStream<T,R>, AssistantMessageEventStream
├── hash.ts                    13L   — shortHash(text)
├── headers.ts                  7L   — headersToRecord(Headers|HeadersInit)
├── json-parse.ts             124L   — repairJson, parseJsonWithRepair, parseStreamingJson
├── overflow.ts               156L   — isContextOverflowError(message, ctx) — provider regex patterns
├── sanitize-unicode.ts        25L   — sanitizeSurrogates(text)
├── typebox-helpers.ts         24L   — TypeBox schema helpers
└── validation.ts             324L   — getValidator, validateToolCall, coerceToolArguments
```

### `src/utils/oauth/` — 7 files, 1,622 LOC

```
utils/oauth/
├── anthropic.ts                  402L   — anthropicOAuthProvider, loginAnthropic, refreshAnthropicToken
├── github-copilot.ts             396L   — githubCopilotOAuthProvider + helpers
├── index.ts                      152L   — registry + dispatch (registerOAuthProvider, getOAuthProvider, refreshOAuthToken, getOAuthApiKey)
├── oauth-page.ts                 109L   — embedded callback HTML
├── openai-codex.ts               458L   — openaiCodexOAuthProvider, loginOpenAICodex, refreshOpenAICodexToken
├── pkce.ts                        34L   — generateCodeVerifier + generateCodeChallenge
└── types.ts                       71L   — OAuthProviderInterface, OAuthCredentials, OAuthLoginCallbacks
```

---

## 2. Universal interface (`api-registry.ts` — 98L)

### Public types (verbatim)

```ts
export type ApiStreamFunction = (
  model: Model<Api>,
  context: Context,
  options?: StreamOptions,
) => AssistantMessageEventStream;

export type ApiStreamSimpleFunction = (
  model: Model<Api>,
  context: Context,
  options?: SimpleStreamOptions,
) => AssistantMessageEventStream;

export interface ApiProvider<
  TApi extends Api = Api,
  TOptions extends StreamOptions = StreamOptions,
> {
  api: TApi;
  stream: StreamFunction<TApi, TOptions>;
  streamSimple: StreamFunction<TApi, SimpleStreamOptions>;
}
```

Note: `ApiProvider` has **exactly two methods** (`stream`, `streamSimple`). Both return `AssistantMessageEventStream` — no non-streaming path exists in the surface.

### Registry storage shape

```ts
interface ApiProviderInternal {
  api: Api;
  stream: ApiStreamFunction;
  streamSimple: ApiStreamSimpleFunction;
}
type RegisteredApiProvider = { provider: ApiProviderInternal; sourceId?: string };

const apiProviderRegistry: Map<string, RegisteredApiProvider>;
```

### Public functions

```ts
export function registerApiProvider<TApi extends Api, TOptions extends StreamOptions>(
  provider: ApiProvider<TApi, TOptions>,
  sourceId?: string,
): void;

export function getApiProvider(api: Api): ApiProviderInternal | undefined;
export function getApiProviders(): ApiProviderInternal[];
export function unregisterApiProviders(sourceId: string): void;
export function clearApiProviders(): void;
```

**Pattern:** Type-safe `wrapStream()` / `wrapStreamSimple()` internal adapters validate API mismatch at runtime. Registration is keyed by `api` (the string identifier — `"anthropic-messages"`, `"openai-completions"`, etc.).

---

## 3. Universal types (`types.ts` — 565L)

### Message discriminated union

```ts
export interface UserMessage {
  role: "user";
  content: string | (TextContent | ImageContent)[];
  timestamp: number;
}

export interface AssistantMessage {
  role: "assistant";
  content: (TextContent | ThinkingContent | ToolCall)[];
  api: Api;
  provider: Provider;
  model: string;
  responseModel?: string;
  responseId?: string;
  diagnostics?: AssistantMessageDiagnostic[];
  usage: Usage;
  stopReason: StopReason;
  errorMessage?: string;
  timestamp: number;
}

export interface ToolResultMessage<TDetails = any> {
  role: "toolResult";
  toolCallId: string;
  toolName: string;
  content: (TextContent | ImageContent)[];
  details?: TDetails;
  isError: boolean;
  timestamp: number;
}

export type Message = UserMessage | AssistantMessage | ToolResultMessage;
```

Note: only **three** message roles. No `"system"` role on `Message`; system prompt lives on `Context.systemPrompt`. No tool-use role; tool calls are content blocks inside `AssistantMessage`.

### Content blocks

```ts
export interface TextContent       { type: "text";     text: string; textSignature?: string; }
export interface ThinkingContent   { type: "thinking"; thinking: string; thinkingSignature?: string; redacted?: boolean; }
export interface ImageContent      { type: "image";    data: string; mimeType: string; }
export interface ToolCall          { type: "toolCall"; id: string; name: string; arguments: Record<string, any>; thoughtSignature?: string; }
```

`thinkingSignature` / `thoughtSignature` carry encrypted reasoning context for replay (Anthropic, Google). `redacted` flags Anthropic redacted-thinking blocks.

### Usage & stop reason

```ts
export interface Usage {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  totalTokens: number;
  cost: { input: number; output: number; cacheRead: number; cacheWrite: number; total: number };
}

export type StopReason = "stop" | "length" | "toolUse" | "error" | "aborted";
```

### Stream options

```ts
export interface StreamOptions {
  temperature?: number;
  maxTokens?: number;
  signal?: AbortSignal;
  apiKey?: string;
  transport?: Transport;
  cacheRetention?: CacheRetention;
  sessionId?: string;
  onPayload?: (payload: unknown, model: Model<Api>) => unknown | undefined | Promise<...>;
  onResponse?: (response: ProviderResponse, model: Model<Api>) => void | Promise<void>;
  headers?: Record<string, string>;
  timeoutMs?: number;
  maxRetries?: number;
  maxRetryDelayMs?: number;
  metadata?: Record<string, unknown>;
}

export interface SimpleStreamOptions extends StreamOptions {
  reasoning?: ThinkingLevel;   // "minimal"|"low"|"medium"|"high"|"xhigh"
  thinkingBudgets?: ThinkingBudgets;
}
```

### Compat overrides (per-provider tuning at model granularity)

```ts
export interface OpenAICompletionsCompat { /* maxTokensField, reasoningField, thinkingFormat, ... */ }
export interface OpenAIResponsesCompat   { /* ... */ }
export interface AnthropicMessagesCompat { /* ... */ }
export interface OpenRouterRouting       { /* provider preferences */ }
export interface VercelGatewayRouting    { /* ... */ }
```

### Event protocol (the universal stream)

```ts
export type AssistantMessageEvent =
  | { type: "start";            partial: AssistantMessage }
  | { type: "text_start";       contentIndex: number; partial: AssistantMessage }
  | { type: "text_delta";       contentIndex: number; delta: string; partial: AssistantMessage }
  | { type: "text_end";         contentIndex: number; content: string; partial: AssistantMessage }
  | { type: "thinking_start";   contentIndex: number; partial: AssistantMessage }
  | { type: "thinking_delta";   contentIndex: number; delta: string; partial: AssistantMessage }
  | { type: "thinking_end";     contentIndex: number; content: string; partial: AssistantMessage }
  | { type: "toolcall_start";   contentIndex: number; partial: AssistantMessage }
  | { type: "toolcall_delta";   contentIndex: number; delta: string; partial: AssistantMessage }
  | { type: "toolcall_end";     contentIndex: number; toolCall: ToolCall; partial: AssistantMessage }
  | { type: "done";   reason: Extract<StopReason, "stop"|"length"|"toolUse">;    message: AssistantMessage }
  | { type: "error";  reason: Extract<StopReason, "aborted"|"error">;            error: AssistantMessage };
```

**12 event types total.** Every block (text, thinking, toolcall) has start/delta/end; the stream terminates with exactly one of `done`/`error`. `partial` snapshots the in-progress AssistantMessage on every event so consumers can render without holding their own state.

### Model & Context

```ts
export interface Model<TApi extends Api> {
  id: string;
  name: string;
  api: TApi;
  provider: Provider;
  baseUrl: string;
  reasoning: boolean;
  thinkingLevelMap?: ThinkingLevelMap;       // "minimal"|"low"|"medium"|"high"|"xhigh" → provider value | null (unsupported)
  input: ("text" | "image")[];
  cost: { input: number; output: number; cacheRead: number; cacheWrite: number };
  contextWindow: number;
  maxTokens: number;
  headers?: Record<string, string>;
  compat?: /* conditional type based on TApi: OpenAICompletionsCompat | AnthropicMessagesCompat | ... */;
}

export interface Tool<TParameters extends TSchema = TSchema> {
  name: string;
  description: string;
  parameters: TParameters;        // TypeBox schema
}

export interface Context {
  systemPrompt?: string;
  messages: Message[];
  tools?: Tool[];
}
```

**Context is the entire invocation input** — system prompt + message history + tools. No external state, no session object, no registry of tool handlers (tool *execution* is the caller's job; pi-mono only emits `ToolCall`s and accepts `ToolResultMessage`s back).

### API/Provider enums

```ts
export type KnownApi =
  | "openai-completions"
  | "mistral-conversations"
  | "openai-responses"
  | "azure-openai-responses"
  | "openai-codex-responses"
  | "anthropic-messages"
  | "bedrock-converse-stream"
  | "google-generative-ai"
  | "google-vertex";
export type Api = KnownApi | (string & {});

export type KnownProvider = /* 25 known providers enumerated */;
export type Provider = KnownProvider | string;
```

**9 known APIs** (not 25 — multiple providers share an API; e.g., DeepSeek/Moonshot/Groq/OpenRouter/Together/Cerebras all share `"openai-completions"`).

---

## 4. Stream utilities

### `stream.ts` — 59L

Thin wrappers that resolve `getApiProvider(model.api)` and dispatch:

```ts
export function stream<TApi extends Api>(
  model: Model<TApi>, context: Context, options?: ProviderStreamOptions,
): AssistantMessageEventStream;

export async function complete<TApi extends Api>(
  model: Model<TApi>, context: Context, options?: ProviderStreamOptions,
): Promise<AssistantMessage>;

export function streamSimple<TApi extends Api>(
  model: Model<TApi>, context: Context, options?: SimpleStreamOptions,
): AssistantMessageEventStream;

export async function completeSimple<TApi extends Api>(
  model: Model<TApi>, context: Context, options?: SimpleStreamOptions,
): Promise<AssistantMessage>;

export const getEnvApiKey: (provider: KnownProvider | string) => string | undefined;
```

`complete()` is **NOT** a non-streaming path — it's `stream().result()`. Internally, every code path is streaming. The `complete()` shorthand just awaits the final AssistantMessage.

### `utils/event-stream.ts` — 87L

```ts
export class EventStream<T, R = T> implements AsyncIterable<T> {
  constructor(
    private isComplete: (event: T) => boolean,
    private extractResult: (event: T) => R,
  );

  push(event: T): void;
  end(result?: R): void;
  [Symbol.asyncIterator](): AsyncIterator<T>;
  result(): Promise<R>;
}

export class AssistantMessageEventStream extends EventStream<AssistantMessageEvent, AssistantMessage> {
  constructor();   // wired with isComplete(e) === e.type === "done" || "error"
}

export function createAssistantMessageEventStream(): AssistantMessageEventStream;
```

Queue-based async iteration with backpressure. Terminal `done`/`error` event resolves `result()`. Single shape used by every provider.

---

## 5. Provider files

### `providers/anthropic.ts` (1207L) — REFERENCE DEPTH

**AUTH (lines ~773–881):**
- `createClient(model, apiKey, ...)` — Anthropic SDK with custom defaultHeaders + session affinity
- API key resolution: `options?.apiKey ?? getEnvApiKey(model.provider) ?? ""`
- OAuth detection: `isOAuthToken(apiKey)` — prefix `"sk-ant-oat"`
- Modes: API key | OAuth bearer | GitHub Copilot bearer | Cloudflare AI Gateway custom headers

**MESSAGE TRANSFORM (lines ~994–1156):**
- `convertMessages(messages[], model, isOAuthToken, cacheControl?)`
- Delegates universal-shape normalization to `transformMessages()` (in `providers/transform-messages.ts`)
- `normalizeToolCallId(id)` — alphanumeric + dash/underscore, max 64 chars
- Cache control applied to system prompt + last user message block

**REQUEST BUILD (lines ~883–987):**
- `buildParams(model, context, isOAuthToken, options?)` → `MessageCreateParamsStreaming`
- Params: model, messages, max_tokens, system, tools, thinking, output_config, metadata, tool_choice, temperature (conditional on no thinking)

**STREAM ITERATION (lines ~328–687):**
- `streamAnthropic` (lines ~428–687) is the main handler — registered via `register-builtins.ts`
- SSE decoder: `iterateSseMessages()` (lines ~328–385) — manual line parser (no SDK streaming)
- Event parser: `iterateAnthropicEvents()` (lines ~387–426) — yields `RawMessageStreamEvent`
- State machine handles `message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`
- Emits: `text_start/delta/end`, `thinking_start/delta/end`, `toolcall_start/delta/end` (uses `parseStreamingJson()` for partial JSON args), `done` / `error`
- Usage tracking from `message_start` + `message_delta`
- Cost via `calculateCost(model, usage)`

**SIMPLE WRAPPER:** `streamSimpleAnthropic` (lines ~728–767) maps `SimpleStreamOptions.reasoning` → effort level or thinking budget.

**EXTENSIONS:**
- Adaptive thinking via `supportsAdaptiveThinking(modelId)` (Opus 4.6+, Sonnet 4.6+)
- Thinking display: `"summarized"` (default) vs `"omitted"` (faster TTFT)
- Interleaved thinking via `INTERLEAVED_THINKING_BETA` header
- Fine-grained tool streaming via `FINE_GRAINED_TOOL_STREAMING_BETA` (deprecated on Opus 4.6+)
- Claude Code identity: OAuth requests include system prompt `"You are Claude Code, Anthropic's official CLI for Claude."`
- Copilot vision header injection via `buildCopilotDynamicHeaders()`

**EXPORTS:**
```ts
export type AnthropicEffort = "low" | "medium" | "high" | "xhigh" | "max";
export type AnthropicThinkingDisplay = "summarized" | "omitted";

export interface AnthropicOptions extends StreamOptions {
  thinkingEnabled?: boolean;
  thinkingBudgetTokens?: number;
  effort?: AnthropicEffort;
  thinkingDisplay?: AnthropicThinkingDisplay;
  interleavedThinking?: boolean;
  toolChoice?: "auto" | "any" | "none" | { type: "tool"; name: string };
  client?: Anthropic;
}

export const streamAnthropic: StreamFunction<"anthropic-messages", AnthropicOptions>;
export const streamSimpleAnthropic: StreamFunction<"anthropic-messages", SimpleStreamOptions>;
```

### `providers/openai-completions.ts` (1148L)

**AUTH:** OpenAI SDK client with custom baseURL + defaultHeaders + proxy. API key resolution identical pattern.

**MESSAGE TRANSFORM:** `transformMessages()` → `ChatCompletionMessageParam[]`. Reasoning content stored as `reasoning_content` (o1 models). Tool output → tool-role messages.

**REQUEST BUILD:** `buildParams(model, context, options?, compat, cacheRetention)` → `ChatCompletionCreateParamsStreaming`. Compat detection auto-runs from `model.baseUrl` (OpenAI, Azure, Cloudflare, etc.). `stream_options: { include_usage: true }` always set.

**STREAM ITERATION:** `streamOpenAICompletions` (lines 111–260+). Uses `client.chat.completions.create(...).withResponse()`. Consumes `ChatCompletionChunk` deltas. State machine reconstructs text + reasoning + tool_use blocks. Streaming tool args via `parseStreamingJson()`.

**COMPAT MAPPING:** `thinkingFormat` field handles OpenAI / OpenRouter / DeepSeek / Together / Qwen variants.

**EXPORTS:**
```ts
export interface OpenAICompletionsOptions extends StreamOptions {
  toolChoice?: "auto"|"none"|"required"|{ type: "function"; function: { name: string } };
  reasoningEffort?: "minimal"|"low"|"medium"|"high"|"xhigh";
}
export const streamOpenAICompletions: StreamFunction<"openai-completions", OpenAICompletionsOptions>;
export const streamSimpleOpenAICompletions: StreamFunction<"openai-completions", SimpleStreamOptions>;
```

### `providers/amazon-bedrock.ts` (956L)

**AUTH:** AWS profile | IAM keys | bearer token (`AWS_BEARER_TOKEN_BEDROCK`) | ECS task role | IRSA | ADC. Region from explicit > env > SDK default chain. `BedrockRuntimeClient` (AWS SDK v3). NodeHttpHandler + ProxyAgent for HTTP/1.1 or HTTP/2.

**MESSAGE TRANSFORM:** `transformMessages()` → Bedrock `Message[]` (role + ContentBlock[]).

**REQUEST BUILD:** `buildConverseStreamRequest(model, context, options)` → `ConverseStreamCommand` input. Thinking via `modelParameters.thinkingConfig` budget. Claude 4.x interleaved thinking. Cache via TTL types (`CacheTTL.ONE_HOUR`, etc.).

**STREAM ITERATION:** `streamBedrock` (lines 87+). `ConverseStreamCommand` with `getReader()`. Events: `metadata`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_stop`.

**EXPORTS:**
```ts
export interface BedrockOptions extends StreamOptions {
  region?: string; profile?: string;
  toolChoice?: "auto"|"any"|"none"|{ type: "tool"; name: string };
  reasoning?: ThinkingLevel;
  thinkingBudgets?: ThinkingBudgets;
  interleavedThinking?: boolean;
  thinkingDisplay?: "summarized"|"omitted";
  requestMetadata?: Record<string, string>;
  bearerToken?: string;
}
```

### `providers/google.ts` (501L)

**AUTH:** API key (env GEMINI_API_KEY or option). `GoogleGenAI` from `@google/genai`.

**MESSAGE TRANSFORM:** `convertMessages()` from `google-shared.ts` → `Content[]`.

**REQUEST BUILD:** `buildParams(model, context, options)` → `GenerateContentParameters`. Thinking `budgetTokens` (dynamic = -1, fixed > 0). Level: MINIMAL/LOW/MEDIUM/HIGH.

**STREAM ITERATION:** `client.models.generateContentStream(params)`. Events: `GenerateContentResponse` chunks with `candidates[0].content.parts`. Text vs thinking part tracking. Stateful tool-call ID counter.

**EXPORTS:**
```ts
export interface GoogleOptions extends StreamOptions {
  toolChoice?: "auto"|"none"|"any";
  thinking?: { enabled: boolean; budgetTokens?: number; level?: GoogleThinkingLevel };
}
```

### `providers/google-vertex.ts` (568L)

**AUTH:** Vertex API key (preferred) OR ADC + project/location. `createClientWithApiKey()` vs `createClient()` (ADC). Vertex AI ResourceScope.

**MESSAGE TRANSFORM / REQUEST BUILD / STREAM ITERATION:** Identical to `google.ts` via `google-shared.ts`.

**EXPORTS:** `GoogleVertexOptions extends StreamOptions` adds `project?` / `location?`.

### `providers/google-shared.ts` (350L)

```ts
export type GoogleThinkingLevel = "THINKING_LEVEL_UNSPECIFIED"|"MINIMAL"|"LOW"|"MEDIUM"|"HIGH";

export function isThinkingPart(part): boolean;
export function retainThoughtSignature(existing?: string, incoming?: string): string | undefined;
export function requiresToolCallId(modelId: string): boolean;
export function convertMessages<T extends GoogleApiType>(model: Model<T>, context: Context): Content[];
export function convertTools<T extends GoogleApiType>(model: Model<T>, tools: Tool[]): Tool[];
export function mapToolChoice(choice?): FunctionCallingConfigMode;
export function mapStopReason(reason: FinishReason | string): StopReason;
```

### `providers/mistral.ts` (634L)

**AUTH:** Mistral SDK per-request instance with `serverURL: model.baseUrl`.

**MESSAGE TRANSFORM:** `transformMessages()` → `ChatCompletionStreamRequestMessage[]`.

**REQUEST BUILD:** `buildChatPayload(...)` → `ChatCompletionStreamRequest`. `promptMode: "reasoning"` + `reasoningEffort: "high"|"none"` for R-series.

**STREAM ITERATION:** `mistral.chat.stream(payload)` → `CompletionEvent` chunks. 9-char hash tool-call ID normalization.

### `providers/openai-responses.ts` (295L)

Thin wrapper around `client.responses.create(params).withResponse()`. Delegates parsing to `openai-responses-shared.ts:processResponsesStream()`. `OpenAIResponsesOptions` adds `reasoningEffort`, `reasoningSummary`, `serviceTier`.

### `providers/azure-openai-responses.ts` (281L)

Azure-specific wrapper: API key + `resourceName` + `deploymentId`. Builds Azure baseURL. Otherwise delegates to openai-responses shared logic.

### `providers/openai-codex-responses.ts` (1351L)

ChatGPT Codex OAuth path. **Two transports**: WebSocket (`websocket`, `websocket-cached`) OR HTTP SSE. OAuth via `loginOpenAICodex()` / `refreshOpenAICodexToken()` from `utils/oauth/openai-codex.ts`.

### `providers/cloudflare.ts` (35L) — NOT a provider

```ts
export function resolveCloudflareBaseUrl(model: Model<any>): string;
export function isCloudflareProvider(provider: string): boolean;
```

Cloudflare AI Gateway is consumed via base-URL routing inside other providers.

### `providers/github-copilot-headers.ts` (37L)

```ts
export function buildCopilotDynamicHeaders(options: { messages: Message[]; hasImages: boolean }): Record<string, string>;
export function hasCopilotVisionInput(messages: Message[]): boolean;
```

### `providers/faux.ts` (499L)

Test double; scripted responses. Exports `fauxText`, `fauxThinking`, `fauxToolCall`, `fauxAssistantMessage`, `registerFauxProvider({...})`. Registration returns a control surface (`setResponses`, `appendResponses`, `getPendingResponseCount`, `unregister`, `state.callCount`).

### `providers/simple-options.ts` (50L)

```ts
export function buildBaseOptions(model: Model<Api>, options?: SimpleStreamOptions, apiKey?: string): StreamOptions;
export function clampReasoning(effort: ThinkingLevel | undefined): Exclude<ThinkingLevel, "xhigh"> | undefined;
export function adjustMaxTokensForThinking(
  baseMaxTokens: number, modelMaxTokens: number,
  reasoningLevel: ThinkingLevel, customBudgets?: ThinkingBudgets,
): { maxTokens: number; thinkingBudget: number };
```

### `providers/transform-messages.ts` (220L)

**Single export:**
```ts
export function transformMessages<TApi extends Api>(
  messages: Message[],
  model: Model<TApi>,
  normalizeToolCallId?: (id: string, model: Model<TApi>, source: AssistantMessage) => string,
): Message[];
```

**Transformations:**
1. **Image downgrade** when model lacks vision support
2. **Thinking-block handling** — redacted (encrypted) thinking kept only if same provider/model; empty thinking dropped; cross-model thinking → text content
3. **Tool call ID normalization** via callback
4. **Synthetic tool results** — insert empty `ToolResultMessage` for orphaned `ToolCall`s (API compliance)
5. **Error/abort filtering** — skip incomplete assistant messages with `stopReason: "error" | "aborted"`

Two-pass algorithm. Preserves tool-call ID mapping across turns.

---

## 6. Registry / discovery / builtins (`providers/register-builtins.ts` — 403L)

**Lazy module loaders** with memoization (one import per module). Each provider module is wrapped:

```ts
function createLazyStream<TApi extends Api, TOptions extends StreamOptions, TSimpleOptions extends SimpleStreamOptions>(
  loadModule: () => Promise<LazyProviderModule<TApi, TOptions, TSimpleOptions>>,
): StreamFunction<TApi, TOptions>;
```

**Registration (immediately at module load):**
```ts
export function registerBuiltInApiProviders(): void;
export function resetApiProviders(): void;
export function setBedrockProviderModule(module: BedrockProviderModule): void;  // override hook
```

The 9 built-in APIs registered:
1. `anthropic-messages` → streamAnthropic / streamSimpleAnthropic
2. `openai-completions` → streamOpenAICompletions / streamSimpleOpenAICompletions
3. `mistral-conversations` → streamMistral / streamSimpleMistral
4. `openai-responses` → streamOpenAIResponses / streamSimpleOpenAIResponses
5. `azure-openai-responses` → streamAzureOpenAIResponses / streamSimpleAzureOpenAIResponses
6. `openai-codex-responses` → streamOpenAICodexResponses / streamSimpleOpenAICodexResponses
7. `google-generative-ai` → streamGoogle / streamSimpleGoogle
8. `google-vertex` → streamGoogleVertex / streamSimpleGoogleVertex
9. `bedrock-converse-stream` → streamBedrock / streamSimpleBedrock (with override hook)

`registerBuiltInApiProviders();` is invoked at module load.

---

## 7. OAuth (`utils/oauth/`)

### `oauth.ts` (1L) — re-export `./utils/oauth/index.js`

### `utils/oauth/index.ts` (152L)

Re-exports per-provider symbols + registry:

```ts
export { anthropicOAuthProvider, loginAnthropic, refreshAnthropicToken } from "./anthropic.js";
export { getGitHubCopilotBaseUrl, githubCopilotOAuthProvider, loginGitHubCopilot, normalizeDomain, refreshGitHubCopilotToken } from "./github-copilot.js";
export { loginOpenAICodex, openaiCodexOAuthProvider, refreshOpenAICodexToken } from "./openai-codex.js";
export * from "./types.js";

export function getOAuthProvider(id: OAuthProviderId): OAuthProviderInterface | undefined;
export function registerOAuthProvider(provider: OAuthProviderInterface): void;
export function unregisterOAuthProvider(id: string): void;
export function resetOAuthProviders(): void;
export function getOAuthProviders(): OAuthProviderInterface[];
export function getOAuthProviderInfoList(): OAuthProviderInfo[];
export async function refreshOAuthToken(providerId: OAuthProviderId, credentials: OAuthCredentials): Promise<OAuthCredentials>;
export async function getOAuthApiKey(providerId: OAuthProviderId, credentials: Record<string, OAuthCredentials>): Promise<{ newCredentials: OAuthCredentials; apiKey: string } | null>;
```

### `utils/oauth/types.ts` (71L)

```ts
export type OAuthProviderId = "anthropic" | "github-copilot" | "openai-codex";

export interface OAuthProviderInterface {
  id: OAuthProviderId;
  name: string;
  getAuthUrl(state: string, codeChallenge: string): Promise<string>;
  exchangeCode(code: string, codeVerifier: string): Promise<OAuthCredentials>;
  refreshToken(credentials: OAuthCredentials): Promise<OAuthCredentials>;
  getApiKey(credentials: OAuthCredentials): string;
}

export interface OAuthCredentials {
  accessToken: string;
  refreshToken?: string;
  expiresIn?: number;
  expires: number;        // Unix ms
}

export interface OAuthLoginCallbacks {
  onUrl: (url: string) => void;
  onComplete: (credentials: OAuthCredentials) => void | Promise<void>;
  onError: (error: Error) => void;
}
```

### `utils/oauth/pkce.ts` (34L)

```ts
export function generateCodeVerifier(): string;
export function generateCodeChallenge(codeVerifier: string): Promise<string>;
```

### Per-provider OAuth flows

- `anthropic.ts` (402L): `anthropicOAuthProvider`, `loginAnthropic(callbacks)`, `refreshAnthropicToken(credentials)`
- `github-copilot.ts` (396L): `githubCopilotOAuthProvider`, `loginGitHubCopilot(baseUrl?, callbacks?)`, `refreshGitHubCopilotToken(credentials)`, `normalizeDomain(domain)`, `getGitHubCopilotBaseUrl(domain?)`
- `openai-codex.ts` (458L): `openaiCodexOAuthProvider`, `loginOpenAICodex(callbacks)`, `refreshOpenAICodexToken(credentials)`
- `oauth-page.ts` (109L): embedded HTML callback page

**Three OAuth providers, one shared protocol.** Adding a new provider = implement `OAuthProviderInterface` + register via `registerOAuthProvider()`.

---

## 8. Models (`models.generated.ts` 17,252L, `models.ts` 92L)

### `models.ts`

```ts
export function getModel<TProvider extends KnownProvider, TModelId extends keyof (typeof MODELS)[TProvider]>(
  provider: TProvider, modelId: TModelId,
): Model<ModelApi<TProvider, TModelId>>;

export function getProviders(): KnownProvider[];
export function getModels<TProvider extends KnownProvider>(provider: TProvider): Model<...>[];
export function calculateCost<TApi extends Api>(model: Model<TApi>, usage: Usage): Usage["cost"];
export function getSupportedThinkingLevels<TApi extends Api>(model: Model<TApi>): ModelThinkingLevel[];
export function clampThinkingLevel<TApi extends Api>(model: Model<TApi>, level: ModelThinkingLevel): ModelThinkingLevel;
export function modelsAreEqual<TApi extends Api>(a, b): boolean;
```

### `models.generated.ts`

Nested object keyed by **provider → model ID**:

```ts
const MODELS: Record<KnownProvider, Record<string, Model<Api>>> = {
  anthropic:  { "claude-opus-4-1": {...}, "claude-sonnet-4-6": {...}, /* ... */ },
  openai:     { "gpt-4o": {...}, "gpt-4-turbo": {...}, /* ... */ },
  /* ... 23 other providers */
};
```

Model entry fields (per Section 3 `Model<TApi>`): id, name, api, provider, baseUrl, reasoning, thinkingLevelMap, input modalities, cost (4 dimensions), contextWindow, maxTokens, optional headers, optional compat overrides.

---

## 9. Env keys (`env-api-keys.ts` — 210L)

```ts
export function findEnvKeys(provider: KnownProvider | string): string[] | undefined;
export function getEnvApiKey(provider: KnownProvider | string): string | undefined;
```

**Per-provider env vars** (selected):
| Provider          | Env var(s) |
|-------------------|------------|
| `anthropic`       | `ANTHROPIC_OAUTH_TOKEN` (preferred) \| `ANTHROPIC_API_KEY` |
| `openai`          | `OPENAI_API_KEY` |
| `google`          | `GEMINI_API_KEY` |
| `google-vertex`   | `GOOGLE_CLOUD_API_KEY` (or ADC + `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION`) |
| `amazon-bedrock`  | AWS profile / IAM / `AWS_BEARER_TOKEN_BEDROCK` |
| `github-copilot`  | `COPILOT_GITHUB_TOKEN` \| `GH_TOKEN` \| `GITHUB_TOKEN` |
| `mistral`         | `MISTRAL_API_KEY` |
| (~25 providers total) | ... |

**Special:**
- Vertex AI: checks ADC at `~/.config/gcloud/application_default_credentials.json`
- Bedrock: prefers `AWS_BEARER_TOKEN_BEDROCK`; falls back through credential chain
- Bun workaround: reads `/proc/self/environ` if `process.env` is empty

---

## 10. Utilities

### `utils/validation.ts` (324L)
```ts
export function getValidator(schema: Tool["parameters"]): ReturnType<typeof Compile>;
export function validateToolCall(tool: Tool, toolCall: ToolCall): { valid: true } | { valid: false; errors: string[] };
export function coerceToolArguments(tool: Tool, args: Record<string, unknown>): [Record<string, unknown>, string[]];
```

### `utils/overflow.ts` (156L)
```ts
export function isContextOverflowError(message: AssistantMessage, contextWindow?: number): boolean;
```
30+ provider-specific regex patterns (Anthropic, OpenAI, Google, xAI, Groq, OpenRouter, Together, Copilot, MiniMax, Kimi, Cerebras, Mistral, Ollama, etc.)

### `utils/diagnostics.ts` (45L)
```ts
export interface DiagnosticErrorInfo { name?: string; message: string; stack?: string; code?: string | number; }
export interface AssistantMessageDiagnostic { type: string; timestamp: number; error?: DiagnosticErrorInfo; details?: Record<string, unknown>; }
export function extractDiagnosticError(error: unknown): DiagnosticErrorInfo;
export function createAssistantMessageDiagnostic(type: string, error: unknown, details?: Record<string, unknown>): AssistantMessageDiagnostic;
export function appendAssistantMessageDiagnostic<T extends { diagnostics?: AssistantMessageDiagnostic[] }>(message: T, diagnostic): void;
```

### `utils/json-parse.ts` (124L)
```ts
export function repairJson(json: string): string;
export function parseJsonWithRepair<T>(json: string): T;
export function parseStreamingJson<T>(partial: string): T;
```

### `utils/sanitize-unicode.ts` (25L) — `sanitizeSurrogates(text)`
### `utils/headers.ts` (7L) — `headersToRecord(headers)`
### `utils/hash.ts` (13L) — `shortHash(text)`
### `utils/typebox-helpers.ts` (24L) — TypeBox schema helpers

---

## 11. Other top-level files

### `index.ts` (46L) — public barrel
Re-exports: core (types, api-registry, env-api-keys, models, stream), providers (options types + builtin registration), oauth, utils (event-stream, diagnostics, json-parse, overflow, validation, typebox-helpers), images, session-resources.

### `session-resources.ts` (24L)
Minor helper for compaction (out of refactor scope).

### `cli.ts` (133L)
pi CLI entrypoint (out of refactor scope — agent-hub does not have a CLI in this surface).

### `bedrock-provider.ts` (6L)
Re-export shim (Bedrock SDK is dynamically imported to avoid pulling AWS SDK into bundles that don't need it).

### Images surface (out of refactor scope)
`images-api-registry.ts`, `images.ts`, `image-models.generated.ts`, `image-models.ts`, `providers/images/*` — pi-mono's parallel image-generation registry. Confirms separation: text and image surfaces are independent (matching the task's "image adapters are out of scope" rule).

---

## 12. Counts table

### File and LOC totals

| Directory                         | Files | LOC     |
|-----------------------------------|------:|--------:|
| `src/` (top-level)                |    15 | 18,866  |
| `src/providers/`                  |    17 |  9,086  |
| `src/utils/`                      |     9 |    805  |
| `src/utils/oauth/`                |     7 |  1,622  |
| `src/providers/images/`           |     2 |    237  |
| **TOTAL**                         | **50**| **30,616** |

### Subtract out-of-scope surfaces

| Subtraction                                                  | Files | LOC     |
|--------------------------------------------------------------|------:|--------:|
| Image-only files (`image-models.generated.ts`, `image-models.ts`, `images-api-registry.ts`, `images.ts`, `providers/images/*`) | 6 | 607 |
| Generated model registry (`models.generated.ts`)             |     1 | 17,252  |
| CLI (`cli.ts`)                                               |     1 |    133  |
| **In-scope total (excluding generated/CLI/images)**          | **42**| **12,624** |

### Per-provider sizes (LOC, hand-written)

| Provider area                            | Files | LOC |
|------------------------------------------|------:|----:|
| Anthropic (incl. oauth + headers)        |     3 | 1,646 |
| OpenAI completions                       |     1 | 1,148 |
| OpenAI Codex responses (+ oauth)         |     2 | 1,809 |
| OpenAI responses (+ azure + shared)      |     3 | 1,127 |
| Google (generative-ai + vertex + shared) |     3 | 1,419 |
| Amazon Bedrock                           |     1 |   956 |
| Mistral                                  |     1 |   634 |
| GitHub Copilot OAuth + headers           |     2 |   433 |
| Cloudflare helper                        |     1 |    35 |
| Faux test double                         |     1 |   499 |
| transform-messages.ts                    |     1 |   220 |
| simple-options.ts                        |     1 |    50 |
| **Provider area total**                  |  **20** | **9,976** |

### Comparison hook (filled in convergence-map.md)

> Agent-hub's adapter+harness surface (`backend/app/adapters/` + `backend/app/api/complete/`) is **133 files / 21,835 LOC**. Pi-mono's in-scope hand-written surface is **42 files / 12,624 LOC**. Ratio: **~3.2× file count, ~1.7× LOC**. The "30–50×" figure in the task description was based on raw file counts before excluding pi-mono's generated registry; the real shape problem is the **file fragmentation** (one provider's 18 files vs. pi-mono's one), not absolute LOC.

---

## 13. Architecture summary

### The universal adapter pattern

1. **Registration:** Each provider module exports `streamXxx` / `streamSimpleXxx` of type `StreamFunction<TApi, TOptions>`. `register-builtins.ts` lazy-imports each provider and registers via `registerApiProvider({ api, stream, streamSimple })`.

2. **Dispatch:** Callers invoke `stream(model, context, options)` or `streamSimple(model, context, options)`. Top-level `stream.ts` resolves `getApiProvider(model.api)` and invokes the provider's stream function.

3. **Message normalization:** Providers call `transformMessages(messages, model, normalizeToolCallId?)` before request build. Handles image downgrade, thinking-block carryover, tool-call ID normalization, synthetic tool results, error/abort filtering.

4. **Universal event stream:** Every provider emits `AssistantMessageEvent` discriminated union (12 variants: start, text/thinking/toolcall × start/delta/end, done, error). `partial: AssistantMessage` is included on every event so consumers can render without local state.

5. **Termination:** Every stream ends with exactly one terminal event: `done` (normal stop, length limit, or `toolUse`) or `error` (aborted or error).

6. **Tool execution boundary:** pi-mono **does not execute tools.** It emits `ToolCall`s as content blocks in `AssistantMessage`. The caller (e.g., pi's tool loop) executes the tool and feeds back `ToolResultMessage`s on the next turn. **No tool runtime, no session, no registry of tool handlers inside the adapter layer.**

### Provider implementation contract (checklist per provider file)

- [ ] Exports `streamXxx: StreamFunction<"api-type", ProviderOptions>`
- [ ] Exports `streamSimpleXxx: StreamFunction<"api-type", SimpleStreamOptions>`
- [ ] Exports `ProviderOptions extends StreamOptions` (provider-specific tuning)
- [ ] AUTH: API key + (optional) OAuth via `OAuthProviderInterface`
- [ ] MESSAGE TRANSFORM: universal `Message[]` → provider wire format via `transformMessages()`
- [ ] REQUEST BUILD: assembles the streaming request params
- [ ] STREAM ITERATION: SSE/streaming response → `AssistantMessageEvent`s
- [ ] Cost calculation via `calculateCost(model, usage)`
- [ ] Registration via `register-builtins.ts` lazy loader

### Thinking/reasoning abstraction

- Universal level: `SimpleStreamOptions.reasoning: "minimal"|"low"|"medium"|"high"|"xhigh"`
- Per-model mapping: `Model.thinkingLevelMap?` — universal level → provider value (or `null` = unsupported)
- Per-block carrier: `ThinkingContent` with optional `thinkingSignature` (encrypted context replay)
- Provider strategies: Anthropic (adaptive + budget), OpenAI (`reasoning_effort`), Google (dynamic budget), Bedrock (budget)

### Cache & session

- `StreamOptions.cacheRetention: "none"|"short"|"long"` — provider-specific TTL (Anthropic 5min vs 1h, Bedrock cache points, etc.)
- `StreamOptions.sessionId?` — provider session affinity (e.g., `x-session-affinity` for Anthropic Fireworks)
- Cache markers applied to system prompt + last user message block

### What pi-mono does NOT include

- **Tool execution** (caller's job)
- **Multi-turn tool loops** (caller's job)
- **Session persistence** (caller's job)
- **Database storage** (caller's job)
- **HTTP server / endpoints** (the package is a library, not a service)
- **Memory injection** (caller's job)
- **Routing / fallback** (caller picks the model and calls `stream(model, ...)`)
- **Non-streaming code paths** (`complete()` is `stream().result()`)
