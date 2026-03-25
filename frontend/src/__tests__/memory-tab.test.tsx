import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemoryTab } from "@/app/agents/[slug]/components/MemoryTab";
import type { Agent } from "@/app/agents/[slug]/types";

function makeFormData(overrides: Partial<Agent> = {}): Partial<Agent> {
  return {
    memory_config: {
      injection_enabled: true,
      include_mandates: true,
      include_guardrails: true,
      include_references: true,
      continuity_enabled: true,
      continuity_max_sessions: 5,
      audience_tags: [],
      exclude_tags: [],
    },
    effective_memory_config: {
      injection_enabled: true,
      include_mandates: true,
      include_guardrails: true,
      include_references: true,
      continuity_enabled: true,
      continuity_max_sessions: 5,
      audience_tags: [],
      exclude_tags: [],
    },
    ...overrides,
  };
}

describe("MemoryTab", () => {
  it("seeds custom settings from the effective backend config", () => {
    const updateField = vi.fn();
    const inheritedConfig = {
      injection_enabled: false,
      include_mandates: false,
      include_guardrails: false,
      include_references: false,
      continuity_enabled: false,
      continuity_max_sessions: 7,
      audience_tags: [],
      exclude_tags: [],
    };

    render(
      <MemoryTab
        formData={makeFormData({
          memory_config: null,
          effective_memory_config: inheritedConfig,
        })}
        updateField={updateField}
      />
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Enable Custom Memory Settings" })
    );

    expect(updateField).toHaveBeenCalledWith("memory_config", inheritedConfig);
  });

  it("clears subordinate options when memory injection is turned off", () => {
    const updateField = vi.fn();

    render(<MemoryTab formData={makeFormData()} updateField={updateField} />);

    fireEvent.click(screen.getByRole("button", { name: "Memory Injection" }));

    expect(updateField).toHaveBeenCalledWith("memory_config", {
      injection_enabled: false,
      include_mandates: false,
      include_guardrails: false,
      include_references: false,
      continuity_enabled: false,
      continuity_max_sessions: 5,
      audience_tags: [],
      exclude_tags: [],
    });
  });

  it("disables subordinate controls when memory injection is already off", () => {
    const updateField = vi.fn();

    render(
      <MemoryTab
        formData={makeFormData({
          memory_config: {
            injection_enabled: false,
            include_mandates: false,
            include_guardrails: false,
            include_references: false,
            continuity_enabled: false,
            continuity_max_sessions: 5,
            audience_tags: [],
            exclude_tags: [],
          },
        })}
        updateField={updateField}
      />
    );

    expect(screen.getByRole("button", { name: "Include Mandates" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Include Guardrails" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Include References" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Session Continuity" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Memory Injection" })).not.toBeDisabled();
  });
});
