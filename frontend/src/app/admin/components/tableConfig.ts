export const REFRESH_OPTIONS = [
  { value: 0, label: "Manual" },
  { value: 5000, label: "5s" },
  { value: 15000, label: "15s" },
  { value: 30000, label: "30s" },
] as const;

export type RefreshInterval = (typeof REFRESH_OPTIONS)[number]["value"];

export const TABLE_GRID_COLS = "grid-cols-[120px_140px_1fr_200px_32px]";
