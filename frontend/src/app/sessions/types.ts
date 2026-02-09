export const REFRESH_OPTIONS = [
  { value: 0, label: "Manual" },
  { value: 5000, label: "5s" },
  { value: 15000, label: "15s" },
  { value: 30000, label: "30s" },
  { value: 60000, label: "60s" },
] as const;

export type RefreshInterval = (typeof REFRESH_OPTIONS)[number]["value"];
export type SortField = "project" | "model" | "status" | "tokens" | "cost" | "time";
export type SortDirection = "asc" | "desc";

export const REFRESH_STORAGE_KEY = "sessions-auto-refresh";
export const SORT_STORAGE_KEY = "sessions-sort";
