/**
 * Where a running turn is. Same names as the backend's `turn_phase` (`waiting_for_model`, `thinking`, `responding`,
 * `running_tool[:name]`, `retrying`), worked out from the events as they arrive so the label is live between
 * session reads. `null` once the turn has ended.
 */
export function phaseForEvent(event: { type: string; tool_name?: string }): string | null | undefined {
  switch (event.type) {
    case "connected":
    case "tool_result":
      return "waiting_for_model";
    case "thinking":
      return "thinking";
    case "content":
      return "responding";
    case "tool_use":
    case "tool_start":
      return event.tool_name ? `running_tool:${event.tool_name}` : "running_tool";
    case "turn_retry":
      return "retrying";
    case "done":
    case "error":
    case "cancel_acknowledged":
    case "idle":
      return null;
    default:
      return undefined; // an event that does not change the phase
  }
}

/** A short label for the UI. */
export function describePhase(phase: string | null | undefined): string | null {
  if (!phase) return null;
  const [name, detail] = phase.split(":", 2);
  switch (name) {
    case "waiting_for_model":
      return "Waiting for the model";
    case "thinking":
      return "Thinking";
    case "responding":
      return "Responding";
    case "running_tool":
      return detail ? `Running ${detail}` : "Running a tool";
    case "retrying":
      return "Retrying";
    default:
      return name.replace(/_/g, " ");
  }
}
