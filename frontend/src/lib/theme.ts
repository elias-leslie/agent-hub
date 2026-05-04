export const THEME_STORAGE_KEY = 'agent-hub-theme'
export const THEME_OPTIONS = ['system', 'light', 'dark'] as const

export type ThemePreference = (typeof THEME_OPTIONS)[number]
export type ResolvedTheme = Exclude<ThemePreference, 'system'>

const THEME_OPTION_SET = new Set<string>(THEME_OPTIONS)

export function isThemePreference(
  value: string | null | undefined,
): value is ThemePreference {
  return typeof value === 'string' && THEME_OPTION_SET.has(value)
}

export function resolveTheme(
  preference: ThemePreference,
  prefersDark: boolean,
): ResolvedTheme {
  if (preference === 'system') {
    return prefersDark ? 'dark' : 'light'
  }
  return preference
}

export function getStoredTheme(
  storage: Storage | null | undefined,
): ThemePreference {
  if (!storage) {
    return 'system'
  }
  try {
    const value = storage.getItem(THEME_STORAGE_KEY)
    return isThemePreference(value) ? value : 'system'
  } catch {
    return 'system'
  }
}

export function persistTheme(preference: ThemePreference): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference)
  } catch {
    // Ignore storage failures and keep the current session usable.
  }
}

export function applyThemePreference(
  preference: ThemePreference,
  prefersDark: boolean,
): ResolvedTheme {
  const resolved = resolveTheme(preference, prefersDark)
  const root = document.documentElement
  root.dataset.themePreference = preference
  root.dataset.theme = resolved
  root.classList.toggle('dark', resolved === 'dark')
  root.style.colorScheme = resolved
  return resolved
}

export const THEME_INIT_SCRIPT = `
(() => {
  const key = "${THEME_STORAGE_KEY}";
  const root = document.documentElement;
  const stored = window.localStorage.getItem(key);
  const preference =
    stored === "light" || stored === "dark" || stored === "system"
      ? stored
      : "system";
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const resolved = preference === "system" ? (prefersDark ? "dark" : "light") : preference;
  root.dataset.themePreference = preference;
  root.dataset.theme = resolved;
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
})();
`
