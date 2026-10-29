/**
 * The transcript layout's three status colours. A host themes them with custom properties (any CSS colour); the
 * defaults are the dark palette's green, blue and red. The tints are mixed from them.
 */
export const OK = "var(--chat-ui-ok, #7ad68a)";
export const WORK = "var(--chat-ui-work, #6fa8ff)";
export const BAD = "var(--chat-ui-bad, #e7867d)";

export const tint = (color: string, percent: number): string =>
  `color-mix(in oklab, ${color} ${percent}%, transparent)`;
