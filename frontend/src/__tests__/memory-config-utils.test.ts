import { describe, expect, it } from "vitest";
import {
  createDefaultConfig,
  parseConfig,
} from "../app/agents/[slug]/components/memory/utils";

describe("parseConfig", () => {
  it("returns the default config when raw is null", () => {
    expect(parseConfig(null)).toEqual(createDefaultConfig());
  });

  it("treats legacy enabled and injection_enabled as a combined gate", () => {
    expect(
      parseConfig({ enabled: false, injection_enabled: true }).injection_enabled
    ).toBe(false);
    expect(
      parseConfig({ enabled: true, injection_enabled: false }).injection_enabled
    ).toBe(false);
    expect(
      parseConfig({ enabled: true, injection_enabled: true }).injection_enabled
    ).toBe(true);
  });

  it("defaults missing flags to enabled", () => {
    expect(parseConfig({}).injection_enabled).toBe(true);
  });

  it("clears subordinate flags when memory injection is disabled", () => {
    expect(
      parseConfig({
        injection_enabled: false,
        include_mandates: true,
        include_guardrails: true,
        include_references: true,
        continuity_enabled: true,
      })
    ).toMatchObject({
      injection_enabled: false,
      include_mandates: false,
      include_guardrails: false,
      include_references: false,
      continuity_enabled: false,
    });
  });

  it("preserves unknown extension keys while normalizing core fields", () => {
    expect(
      parseConfig({
        include_references: false,
        cross_project_enabled: true,
        query_reference_selection_enabled: true,
      })
    ).toMatchObject({
      include_references: false,
      cross_project_enabled: true,
      query_reference_selection_enabled: true,
    });
  });
});
