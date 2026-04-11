import { useAppStore, getEffectiveTheme } from '@/stores/app.store'

export function useTheme() {
  const { theme, setTheme } = useAppStore()
  const effectiveTheme = getEffectiveTheme(theme)

  return {
    theme,
    effectiveTheme,
    setTheme,
    isDark: effectiveTheme === 'dark',
  }
}
