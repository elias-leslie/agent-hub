'use client'

import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from 'react'
import {
  applyThemePreference,
  getStoredTheme,
  persistTheme,
  type ResolvedTheme,
  type ThemePreference,
} from '@/lib/theme'

interface ThemeContextValue {
  theme: ThemePreference
  resolvedTheme: ResolvedTheme
  setTheme: (theme: ThemePreference) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function getInitialThemePreference(): ThemePreference {
  if (typeof document === 'undefined') {
    return 'system'
  }
  const value = document.documentElement.dataset.themePreference
  return value === 'light' || value === 'dark' || value === 'system'
    ? value
    : 'system'
}

function getInitialResolvedTheme(): ResolvedTheme {
  if (typeof document === 'undefined') {
    return 'dark'
  }
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemePreference>(
    getInitialThemePreference,
  )
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(
    getInitialResolvedTheme,
  )

  useEffect(() => {
    const storedTheme = getStoredTheme(window.localStorage)
    if (storedTheme !== theme) {
      setThemeState(storedTheme)
    }
  }, [theme])

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const syncTheme = (nextTheme: ThemePreference) => {
      setResolvedTheme(applyThemePreference(nextTheme, mediaQuery.matches))
    }

    syncTheme(theme)

    const handleChange = () => {
      if (theme === 'system') {
        syncTheme('system')
      }
    }

    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [theme])

  const setTheme = (nextTheme: ThemePreference) => {
    persistTheme(nextTheme)
    setThemeState(nextTheme)
  }

  return (
    <ThemeContext.Provider value={{ theme, resolvedTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useTheme must be used within ThemeProvider')
  }
  return context
}
