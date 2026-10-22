// Evaluation configuration and content-free observation, using Pi's public hooks.
import { appendFileSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createHash } from "node:crypto";

export default function trial(pi) {
  const condition = JSON.parse(readFileSync(resolve(process.cwd(), "condition.json"), "utf8"));
  const record = (value) => appendFileSync(resolve(process.cwd(), "pi-receipts.jsonl"), JSON.stringify({at: Date.now(), ...value}) + "\n");
  let expectedSystem = "";
  pi.on("before_agent_start", (event) => {
    const payload = readFileSync(condition.context_payload, "utf8");
    // Pi 1.4 project exclusions do not disable auto-discovered user resources.
    // AH is the only other file extension here. Replace its forced additive
    // transport through the documented structured options, preserving every
    // native section, tool, context file, skill and guideline. Required AH
    // bytes are separately verified equal in both frozen previews.
    const priorForced = event.systemPromptOptions.forceSystemPrompt;
    delete event.systemPromptOptions.forceSystemPrompt;
    const native = event.systemPrompt;
    expectedSystem = `${native}\n\n${payload}`;
    record({type: "context", transport: "native-plus-frozen-preview-v4", prior_forced_bytes: priorForced ? Buffer.byteLength(priorForced) : 0, native_bytes: Buffer.byteLength(native), native_sha256: createHash("sha256").update(native).digest("hex"), bytes: Buffer.byteLength(payload), sha256: createHash("sha256").update(payload).digest("hex"), expected_system_sha256: createHash("sha256").update(expectedSystem).digest("hex")});
    return {systemPrompt: expectedSystem};
  });
  pi.on("session_start", (_event, ctx) => record({type: "session", session_id: ctx.sessionManager.getSessionId(), model: ctx.model?.id, provider: ctx.model?.provider, thinking: pi.getThinkingLevel(), tools: pi.getActiveTools()}));
  pi.on("before_provider_request", (event) => {
    const p = event.payload;
    // Pi's forced-prompt projection runs after context_with_system. Apply the
    // experiment transport at the documented serialized-request hook instead.
    // Replace only a leading native+frozen string followed by AH's additional
    // context; preserve roles, tools, safety sections, headers and all history.
    let replaced = 0;
    for (const message of p.input || []) {
      if (message.role !== "system" && message.role !== "developer") continue;
      if (typeof message.content === "string" && message.content.startsWith(expectedSystem)) {
        message.content = expectedSystem;
        replaced += 1;
      } else if (Array.isArray(message.content)) {
        for (const block of message.content) {
          if (typeof block.text === "string" && block.text.startsWith(expectedSystem)) {
            block.text = expectedSystem;
            replaced += 1;
          }
        }
      }
    }
    // Never retain payload content or request headers.
    const serialized = JSON.stringify(p);
    const strings = [];
    const visit = (value) => { if (typeof value === "string") strings.push(value); else if (value && typeof value === "object") Object.values(value).forEach(visit); };
    visit(p);
    record({type: "request", transport: "serialized-system-field-v4", replaced_system_fields: replaced, system_exactly_expected: strings.includes(expectedSystem), payload_keys: Object.keys(p), bytes: Buffer.byteLength(serialized), sha256: createHash("sha256").update(serialized).digest("hex"), model: p.model, reasoning: p.reasoning, service_tier: p.service_tier, input_items: p.input?.length, tools: (p.tools || []).map(t => t.name || t.type)});
    return p;
  });
  pi.on("tool_execution_start", (event) => record({type: "tool_start", id: event.toolCallId, name: event.toolName}));
  pi.on("tool_execution_end", (event) => record({type: "tool_end", id: event.toolCallId, name: event.toolName, error: event.isError}));
  pi.on("message_end", (event) => {
    const m = event.message;
    if (m.role === "assistant") record({type: "response", model: m.model, provider: m.provider, api: m.api, usage: m.usage, stop_reason: m.stopReason, error: m.errorMessage});
  });
  pi.on("session_compact", () => record({type: "compaction"}));
  pi.on("agent_settled", (_event, ctx) => record({type: "settled", session_id: ctx.sessionManager.getSessionId()}));
}
