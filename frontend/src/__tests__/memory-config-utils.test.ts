import { describe, expect, it } from "vitest";
import { parseConfig } from "../app/agents/[slug]/components/memory/utils";

const fallback = {
  injection_enabled: false,
  project_index_enabled: true,
  tool_capabilities_enabled: true,
  include_mandates: false,
  include_guardrails: false,
  include_references: false,
  reference_index_enabled: false,
  continuity_enabled: false,
  continuity_max_sessions: 7,
  audience_tags: ["persona"],
  exclude_tags: ["draft"],
  exclude_memory_uuids: [],
};

describe("parseConfig", () => {
  it("falls back to the provided effective config when fields are omitted", () => {
    expect(parseConfig({}, fallback)).toEqual(fallback);
  });

  it("treats legacy enabled and injection_enabled as a combined gate", () => {
    expect(
      parseConfig({ enabled: false, injection_enabled: true }, fallback)
        .injection_enabled
    ).toBe(false);
    expect(
      parseConfig({ enabled: true, injection_enabled: false }, fallback)
        .injection_enabled
    ).toBe(false);
    expect(
      parseConfig(
        { enabled: true, injection_enabled: true },
        { ...fallback, injection_enabled: true }
      ).injection_enabled
    ).toBe(true);
  });

  it("uses the fallback values instead of hardcoded enabled defaults", () => {
    expect(
      parseConfig({ include_references: true }, fallback)
    ).toMatchObject({
      ...fallback,
      include_references: false,
    });
  });

  it("clears subordinate flags when memory injection is disabled", () => {
    expect(
      parseConfig(
        {
          injection_enabled: false,
          include_mandates: true,
          include_guardrails: true,
          include_references: true,
          reference_index_enabled: true,
          continuity_enabled: true,
        },
        {
          ...fallback,
          injection_enabled: true,
          include_mandates: true,
          include_guardrails: true,
          include_references: true,
          reference_index_enabled: true,
          continuity_enabled: true,
        }
      )
    ).toMatchObject({
      injection_enabled: false,
      include_mandates: false,
      include_guardrails: false,
      include_references: false,
      reference_index_enabled: false,
      continuity_enabled: false,
    });
  });

  it("preserves unknown extension keys while normalizing core fields", () => {
    expect(
      parseConfig(
        {
          include_references: true,
          cross_project_enabled: true,
          query_reference_selection_enabled: true,
        },
        {
          ...fallback,
          injection_enabled: true,
          include_mandates: true,
          include_guardrails: true,
          include_references: false,
          reference_index_enabled: true,
          continuity_enabled: true,
        }
      )
    ).toMatchObject({
      include_references: true,
      cross_project_enabled: true,
      query_reference_selection_enabled: true,
    });
  });

  it("normalizes consumer profile overrides without treating them as opaque extras", () => {
    expect(
      parseConfig(
        {
          runtime_consumer_profile: " agent_coding ",
          preview_consumer_profile: "",
          consumer_profile: "agent_general",
        },
        fallback
      )
    ).toMatchObject({
      runtime_consumer_profile: "agent_coding",
      preview_consumer_profile: undefined,
      consumer_profile: "agent_general",
    });
  });
});
