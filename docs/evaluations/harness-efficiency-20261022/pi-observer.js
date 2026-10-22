// Evaluation configuration and content-free observation, using Pi's public hooks.
import { appendFileSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createHash } from "node:crypto";

export default function trial(pi) {
  const condition = JSON.parse(readFileSync(resolve(process.cwd(), "condition.json"), "utf8"));
  const record = (value) => appendFileSync(resolve(process.cwd(), "pi-receipts.jsonl"), JSON.stringify({at: Date.now(), ...value}) + "\n");
  pi.on("before_agent_start", (event) => {
    const payload = readFileSync(condition.context_payload, "utf8");
    record({type: "context", bytes: Buffer.byteLength(payload), sha256: createHash("sha256").update(payload).digest("hex")});
    return {systemPrompt: `${event.systemPrompt}\n\n${payload}`};
  });
  pi.on("session_start", (_event, ctx) => record({type: "session", session_id: ctx.sessionManager.getSessionId(), model: ctx.model?.id, provider: ctx.model?.provider, thinking: pi.getThinkingLevel(), tools: pi.getActiveTools()}));
  pi.on("before_provider_request", (event) => {
    const p = event.payload;
    // Never retain payload content or request headers.
    const serialized = JSON.stringify(p);
    record({type: "request", bytes: Buffer.byteLength(serialized), sha256: createHash("sha256").update(serialized).digest("hex"), model: p.model, reasoning: p.reasoning, service_tier: p.service_tier, input_items: p.input?.length, tools: (p.tools || []).map(t => t.name || t.type)});
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
