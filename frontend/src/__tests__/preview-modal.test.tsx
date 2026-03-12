import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PreviewModal } from "@/app/agents/[slug]/components/PreviewModal";
import type { AgentPreview } from "@/app/agents/[slug]/types";

const preview: AgentPreview = {
  slug: "persona",
  name: "Jenny",
  combined_prompt: "<system>system only</system>",
  full_context: "<system>system only</system>\n\n<task>Do the heartbeat</task>",
  memory_query: "heartbeat project state",
  loaded_memory_uuids: ["12345678-aaaa", "87654321-bbbb"],
  reference_uuids: ["87654321-bbbb"],
  mandate_count: 2,
  guardrail_count: 1,
  mandate_uuids: ["12345678"],
  guardrail_uuids: ["87654321"],
  task_type: "heartbeat",
  phase: null,
  project_id: null,
  task_prompt: "Do the heartbeat",
  sections: [
    {
      label: "Platform Context",
      source_kind: "global_prompt",
      source_id: "platform-context",
      placement: "system",
      content_hash: "abcd1234",
      chars: 32,
      estimated_tokens: 8,
      content: "<platform>db prompt</platform>",
      role: null,
      priority: null,
      updated_at: null,
    },
    {
      label: "Task Prompt",
      source_kind: "task_prompt",
      source_id: "heartbeat",
      placement: "user",
      content_hash: "beef5678",
      chars: 17,
      estimated_tokens: 4,
      content: "Do the heartbeat",
      role: null,
      priority: null,
      updated_at: null,
    },
  ],
};

describe("PreviewModal", () => {
  it("renders ordered sections and the full context block", () => {
    render(<PreviewModal preview={preview} previewMode="heartbeat" onClose={vi.fn()} />);

    expect(screen.getByText("Combined Prompt Preview")).toBeInTheDocument();
    expect(screen.getByText("Platform Context")).toBeInTheDocument();
    expect(screen.getByText("Task Prompt")).toBeInTheDocument();
    expect(screen.getByText("Full Context")).toBeInTheDocument();
    expect(screen.getByText("Memory Query")).toBeInTheDocument();
    expect(screen.getByText("Loaded Memory UUIDs")).toBeInTheDocument();
    expect(screen.getByText("<platform>db prompt</platform>")).toBeInTheDocument();
    expect(screen.getAllByText("Do the heartbeat").length).toBeGreaterThan(0);
  });
});
