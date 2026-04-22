import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PersonaPromptBudgetPanel } from "@/app/persona/components/PersonaPromptBudgetPanel";

describe("PersonaPromptBudgetPanel", () => {
  it("prefers runtime context while still surfacing preview total compactly", () => {
    render(
      <PersonaPromptBudgetPanel
        loading={false}
        error={null}
        runtimeContext={{
          used_tokens: 2400,
          limit_tokens: 8000,
          percent_used: 30,
          remaining_tokens: 5600,
          warning: null,
        }}
        preview={{
          slug: "persona",
          name: "Avery",
          combined_prompt: "system",
          full_context: "system",
          memory_query: "status",
          memory_debug: { total_tokens: 9100 },
          loaded_memory_uuids: [],
          reference_uuids: [],
          mandate_count: 0,
          guardrail_count: 0,
          mandate_uuids: [],
          guardrail_uuids: [],
          task_type: "chat",
          phase: null,
          project_id: "agent-hub",
          task_prompt: "status",
          sections: [],
        }}
      />,
    );

    expect(screen.getAllByText("Runtime").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/30% live used · 5,600 left · preview 9,100/i)).toBeInTheDocument();
  });
});
