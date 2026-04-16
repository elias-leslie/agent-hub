import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PersonaPromptBudgetPanel } from "@/app/persona/components/PersonaPromptBudgetPanel";

describe("PersonaPromptBudgetPanel", () => {
  it("labels preview-derived prompt totals explicitly", () => {
    render(
      <PersonaPromptBudgetPanel
        loading={false}
        error={null}
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

    expect(
      screen.getByText(/Treat as guidance until runtime publishes authoritative totals/i),
    ).toBeInTheDocument();
  });
});
