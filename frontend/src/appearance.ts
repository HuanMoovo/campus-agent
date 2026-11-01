export type AppearanceMode = 'system' | 'light' | 'dark'

// Retained for persisted workspace compatibility. Visible colours come from tokens.css.
export const DEFAULT_ACCENT = '#202020'

export function normalizeAccent(value: unknown): string | null {
  return typeof value === 'string' && /^#[\da-f]{6}$/i.test(value.trim())
    ? value.trim().toLowerCase()
    : null
}

export function applyAppearance(mode: AppearanceMode, _accent: string, systemDark: boolean): void {
  const dark = mode === 'dark' || (mode === 'system' && systemDark)
  const root = document.documentElement
  root.dataset.theme = dark ? 'dark' : 'light'
  root.style.colorScheme = dark ? 'dark' : 'light'
  // Clear overrides from the previous runtime palette, including during hot reload.
  // The saved accent remains readable by older clients but no longer affects the UI.
  const legacyVariables = [
    '--accent', '--accent-text', '--on-accent', '--accent-hover', '--accent-soft',
    '--accent-border', '--accent-focus', '--el-color-primary', '--el-color-primary-dark-2',
  ]
  for (const level of [3, 5, 7, 8, 9]) {
    legacyVariables.push(`--el-color-primary-light-${level}`)
  }
  for (const name of legacyVariables) root.style.removeProperty(name)
}
