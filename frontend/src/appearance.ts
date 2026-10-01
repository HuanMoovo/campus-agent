export type AppearanceMode = 'system' | 'light' | 'dark'

export const DEFAULT_ACCENT = '#147b75'

export function normalizeAccent(value: unknown): string | null {
  return typeof value === 'string' && /^#[\da-f]{6}$/i.test(value.trim())
    ? value.trim().toLowerCase()
    : null
}

function rgb(hex: string): number[] {
  return [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16))
}

function mix(color: string, target: string, amount: number): string {
  const end = rgb(target)
  return '#' + rgb(color).map((value, index) =>
    Math.round(value + (end[index] - value) * amount).toString(16).padStart(2, '0'),
  ).join('')
}

function luminance(color: string): number {
  const channels = rgb(color).map(value => {
    const channel = value / 255
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  })
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
}

function contrast(a: string, b: string): number {
  const values = [luminance(a), luminance(b)].sort((left, right) => left - right)
  return (values[1] + 0.05) / (values[0] + 0.05)
}

function readableAccent(accent: string, surface: string, dark: boolean): string {
  const target = dark ? '#ffffff' : '#000000'
  for (let step = 0; step <= 100; step++) {
    const candidate = mix(accent, target, step / 100)
    if (contrast(candidate, surface) >= 4.8) return candidate
  }
  return target
}

export function applyAppearance(mode: AppearanceMode, accent: string, systemDark: boolean): void {
  const dark = mode === 'dark' || (mode === 'system' && systemDark)
  const root = document.documentElement
  const color = normalizeAccent(accent) || DEFAULT_ACCENT
  const surface = dark ? '#202124' : '#ffffff'
  const onAccent = contrast(color, '#ffffff') >= contrast(color, '#000000') ? '#ffffff' : '#000000'
  const text = readableAccent(color, dark ? '#282a2d' : '#f1f3f4', dark)
  const hover = mix(color, onAccent === '#ffffff' ? '#000000' : '#ffffff', 0.13)
  root.dataset.theme = dark ? 'dark' : 'light'
  root.style.colorScheme = dark ? 'dark' : 'light'
  const variables: Record<string, string> = {
    '--accent': color,
    '--accent-text': text,
    '--on-accent': onAccent,
    '--accent-hover': hover,
    '--accent-soft': mix(color, surface, dark ? 0.84 : 0.92),
    '--accent-border': mix(color, surface, dark ? 0.48 : 0.64),
    '--accent-focus': mix(color, surface, dark ? 0.65 : 0.78),
    '--el-color-primary': text,
    '--el-color-primary-dark-2': dark ? mix(text, '#ffffff', 0.16) : mix(text, '#000000', 0.16),
  }
  for (const level of [3, 5, 7, 8, 9]) {
    variables[`--el-color-primary-light-${level}`] = mix(text, surface, level / 10)
  }
  for (const [name, value] of Object.entries(variables)) root.style.setProperty(name, value)
}
