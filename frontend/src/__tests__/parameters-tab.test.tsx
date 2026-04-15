import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ParametersTab } from "@/app/agents/[slug]/components/ParametersTab";
import type { Agent, ModelInfo } from "@/app/agents/[slug]/types";

const baseFormData: Partial<Agent> = {
  primary_model_id: "codex/gpt-5.4",
  temperature: 0.7,
  thinking_level: "medium",
  verbosity_level: "high",
  max_concurrency: 4,
  max_subagent_concurrency: 2,
  daily_token_budget: 100000,
  hourly_request_limit: 30,
  timeout_seconds: 60,
};

const codexModel: ModelInfo = {
  id: "codex/gpt-5.4",
  name: "GPT-5.4 (Codex)",
  provider: "codex",
  alias: "codex-5.4",
  hint: "Frontier",
  cost: {
    input_per_m: 2.5,
    output_per_m: 15,
    pricing_unit: "per_million_tokens",
    unit_price: null,
    source: "catalog",
  },
  scores: {
    coding: 82,
    reasoning: 84,
    planning: 80,
    tool_use: 88,
    instruction: 85,
    design: 74,
    composite: 82.6,
  },
  context_window: 1_050_000,
  speed_tier: "medium",
  capabilities: {
    can_generate_images: false,
    has_vision: true,
    can_edit_images: false,
    has_thinking: true,
    supports_pdf: true,
    supports_audio: false,
    max_output_tokens: 32768,
    supports_tool_execution: true,
    supports_verbosity: true,
    supports_xhigh: true,
    supports_session_cache: true,
  },
};

const miniModel: ModelInfo = {
  ...codexModel,
  id: "codex/gpt-5.1-codex-mini",
  name: "GPT-5.1 Codex Mini",
  capabilities: {
    ...codexModel.capabilities,
    has_thinking: false,
    supports_tool_execution: false,
    supports_verbosity: false,
    supports_xhigh: false,
  },
};

describe("parameters tab", () => {
  it("renders and updates agent execution limits", () => {
    const updateField = vi.fn();

    render(<ParametersTab formData={baseFormData} updateField={updateField} availableModels={[codexModel]} />);

    fireEvent.change(screen.getByLabelText("Max concurrency"), {
      target: { value: "8" },
    });
    fireEvent.change(screen.getByLabelText("Max subagent concurrency"), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText("Daily token budget"), {
      target: { value: "250000" },
    });
    fireEvent.change(screen.getByLabelText("Hourly request limit"), {
      target: { value: "45" },
    });

    expect(updateField).toHaveBeenCalledWith("max_concurrency", 8);
    expect(updateField).toHaveBeenCalledWith("max_subagent_concurrency", null);
    expect(updateField).toHaveBeenCalledWith("daily_token_budget", 250000);
    expect(updateField).toHaveBeenCalledWith("hourly_request_limit", 45);
  });

  it("ignores out-of-range values that would be rejected by the API", () => {
    const updateField = vi.fn();

    render(<ParametersTab formData={baseFormData} updateField={updateField} availableModels={[codexModel]} />);

    fireEvent.change(screen.getByLabelText("Max concurrency"), {
      target: { value: "0" },
    });
    fireEvent.change(screen.getByLabelText("Max subagent concurrency"), {
      target: { value: "101" },
    });
    fireEvent.change(screen.getByLabelText("Timeout (seconds)"), {
      target: { value: "601" },
    });

    expect(updateField).not.toHaveBeenCalled();
    expect(screen.getAllByText("Enter a whole number between 1 and 100.")).toHaveLength(2);
    expect(screen.getByText("Enter a value between 1 and 600 seconds.")).toBeInTheDocument();
  });

  it("still allows clearing optional numeric overrides", () => {
    const updateField = vi.fn();

    render(<ParametersTab formData={baseFormData} updateField={updateField} availableModels={[codexModel]} />);

    fireEvent.change(screen.getByLabelText("Timeout (seconds)"), {
      target: { value: "" },
    });

    expect(updateField).toHaveBeenCalledWith("timeout_seconds", null);
  });

  it("keeps invalid drafts visible until the user corrects them", () => {
    const updateField = vi.fn();

    render(<ParametersTab formData={baseFormData} updateField={updateField} availableModels={[codexModel]} />);

    const maxConcurrency = screen.getByLabelText("Max concurrency");
    fireEvent.change(maxConcurrency, { target: { value: "0" } });

    expect(maxConcurrency).toHaveValue(0);
    expect(updateField).not.toHaveBeenCalled();

    fireEvent.change(maxConcurrency, { target: { value: "10" } });

    expect(updateField).toHaveBeenCalledWith("max_concurrency", 10);
    expect(screen.queryByText("Enter a whole number between 1 and 100.")).not.toBeInTheDocument();
  });

  it("shows thinking and verbosity controls only when the selected model supports them", () => {
    const updateField = vi.fn();

    const { rerender } = render(
      <ParametersTab formData={baseFormData} updateField={updateField} availableModels={[codexModel, miniModel]} />
    );

    expect(screen.getByLabelText("Thinking Level")).toBeInTheDocument();
    expect(screen.getByLabelText("Verbosity Level")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /xHigh/i })).toBeInTheDocument();

    rerender(
      <ParametersTab
        formData={{ ...baseFormData, primary_model_id: miniModel.id, thinking_level: "medium", verbosity_level: "high" }}
        updateField={updateField}
        availableModels={[codexModel, miniModel]}
      />
    );

    expect(screen.queryByLabelText("Thinking Level")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Verbosity Level")).not.toBeInTheDocument();
    expect(screen.getByText("This model does not support configurable reasoning effort.")).toBeInTheDocument();
    expect(screen.getByText("This model ignores verbosity overrides.")).toBeInTheDocument();
  });
});
