import { describe, expect, it } from "vitest";
import {
  buildAgentUpdatePayload,
  createAgentFormData,
} from "@/app/agents/[slug]/agent-form";
import type { Agent } from "@/app/agents/[slug]/types";

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 1,
    slug: "persona",
    name: "Persona",
    description: "Primary persona agent",
    system_prompt: "You are persona.",
    primary_model_id: "claude-sonnet-4-6",
    fallback_models: ["gemini-3-flash-preview"],
    escalation_model_id: null,
    strategies: {},
    temperature: 0.7,
    thinking_level: "medium",
    verbosity_level: "high",
    is_active: true,
    is_coding_agent: false,
    tool_permissions: null,
    memory_config: null,
    max_concurrency: 4,
    max_subagent_concurrency: 2,
    daily_token_budget: 200000,
    hourly_request_limit: 50,
    timeout_seconds: 90,
    version: 1,
    created_at: "2026-03-06T14:00:00Z",
    updated_at: "2026-03-06T14:00:00Z",
    ...overrides,
  };
}

describe("agent form helpers", () => {
  it("creates editable form data from an agent", () => {
    const formData = createAgentFormData(makeAgent());

    expect(formData.name).toBe("Persona");
    expect(formData.primary_model_id).toBe("claude-sonnet-4-6");
    expect(formData.max_concurrency).toBe(4);
    expect(formData.daily_token_budget).toBe(200000);
    expect(formData.timeout_seconds).toBe(90);
  });

  it("strips empty required fields from update payloads", () => {
    const payload = buildAgentUpdatePayload({
      name: "",
      system_prompt: "",
      primary_model_id: "",
      description: "",
      max_concurrency: 6,
      hourly_request_limit: 30,
      timeout_seconds: null,
    });

    expect(payload).toEqual({
      description: "",
      max_concurrency: 6,
      hourly_request_limit: 30,
      timeout_seconds: null,
    });
  });
});
