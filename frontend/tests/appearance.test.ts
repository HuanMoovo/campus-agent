import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'

import { applyAppearance, DEFAULT_ACCENT, normalizeAccent, type AppearanceMode } from '../src/appearance'

const require = createRequire(import.meta.url)
const elementStyles = readFileSync(require.resolve('element-plus/dist/index.css'), 'utf8')
const tokens = readFileSync(require.resolve('../src/styles/tokens.css'), 'utf8')
const root = document.documentElement
let stylesheets: HTMLStyleElement[]

function channels(color: string): number[] {
  const hex = /^#([\da-f]{6})(?:[\da-f]{2})?$/i.exec(color.trim())
  if (hex) return [0, 2, 4].map(offset => parseInt(hex[1].slice(offset, offset + 2), 16))
  const rgb = /^rgba?\(\s*(\d+)[, ]+\s*(\d+)[, ]+\s*(\d+)/.exec(color.trim())
  if (rgb) return rgb.slice(1, 4).map(Number)
  throw new Error(`Expected a resolved CSS colour, received ${color}`)
}

function contrast(first: string, second: string): number {
  const luminance = (color: string) => channels(color)
    .map(value => value / 255)
    .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
    .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0)
  const [low, high] = [luminance(first), luminance(second)].sort((a, b) => a - b)
  return (high + 0.05) / (low + 0.05)
}

function color(token: string): string {
  return getComputedStyle(root).getPropertyValue(token).trim()
}

beforeEach(() => {
  root.removeAttribute('style')
  delete root.dataset.theme
  stylesheets = [elementStyles, tokens].map(css => {
    const stylesheet = document.createElement('style')
    stylesheet.textContent = css
    document.head.append(stylesheet)
    return stylesheet
  })
})

afterEach(() => {
  stylesheets.forEach(stylesheet => stylesheet.remove())
  root.removeAttribute('style')
  delete root.dataset.theme
})

describe('appearance', () => {
  it('keeps accepting saved hex colours without changing their storage format', () => {
    expect(normalizeAccent('#A1B2C3')).toBe('#a1b2c3')
    expect(normalizeAccent('  #00ff00 ')).toBe('#00ff00')
    for (const value of ['red', '#fff', '#12345', '', null, 12, '#12345g']) {
      expect(normalizeAccent(value)).toBeNull()
    }
  })

  it.each<[AppearanceMode, boolean, string]>([
    ['dark', false, 'dark'],
    ['light', true, 'light'],
    ['system', false, 'light'],
    ['system', true, 'dark'],
  ])('resolves %s mode with system dark=%s to %s', (mode, systemDark, expected) => {
    applyAppearance(mode, DEFAULT_ACCENT, systemDark)
    expect(root.dataset.theme).toBe(expected)
    expect(root.style.colorScheme).toBe(expected)
  })

  it.each<AppearanceMode>(['light', 'dark', 'system'])('ignores saved accent colours in %s mode', mode => {
    applyAppearance(mode, DEFAULT_ACCENT, true)
    const defaultAccent = color('--accent')
    for (const saved of ['#b03a2e', '#f7d94c', '#00ff00', 'invalid']) {
      applyAppearance(mode, saved, true)
      expect(color('--accent')).toBe(defaultAccent)
    }
  })

  it('removes colour overrides left by the previous theme implementation', () => {
    for (const token of ['--accent', '--accent-text', '--on-accent', '--accent-hover', '--accent-soft', '--accent-border', '--accent-focus', '--el-color-primary', '--el-color-primary-dark-2', '--el-color-primary-light-3', '--el-color-primary-light-5', '--el-color-primary-light-7', '--el-color-primary-light-8', '--el-color-primary-light-9']) {
      root.style.setProperty(token, '#ff0000')
    }
    applyAppearance('dark', '#ff0000', false)
    expect(root.style.getPropertyValue('--accent')).toBe('')
    expect(root.style.getPropertyValue('--el-color-primary-light-9')).toBe('')
    expect(channels(color('--accent'))[0]).toBe(channels(color('--accent'))[1])
  })

  it.each<AppearanceMode>(['light', 'dark', 'system'])('renders every app and Element Plus palette colour in grayscale in %s mode', mode => {
    applyAppearance(mode, '#a218f0', true)
    const palette = ['--page', '--surface', '--surface-muted', '--surface-hover', '--text', '--text-secondary', '--text-muted', '--border', '--border-subtle', '--sidebar', '--sidebar-text', '--sidebar-muted', '--warning-text', '--warning-soft', '--warning-border', '--success-text', '--success-soft', '--danger-text', '--accent', '--accent-text', '--on-accent', '--accent-hover', '--accent-soft', '--accent-border', '--accent-focus']
    for (const state of ['primary', 'success', 'warning', 'danger', 'error', 'info']) {
      palette.push(`--el-color-${state}`, `--el-color-${state}-dark-2`)
      for (let level = 1; level <= 9; level++) palette.push(`--el-color-${state}-light-${level}`)
    }
    for (const token of palette) {
      const [red, green, blue] = channels(color(token))
      expect(red, `${token} red/green`).toBe(green)
      expect(green, `${token} green/blue`).toBe(blue)
    }
  })

  it.each<AppearanceMode>(['light', 'dark'])('keeps text and action labels readable in %s mode', mode => {
    applyAppearance(mode, '#f7d94c', false)
    for (const surface of ['--page', '--surface', '--surface-muted', '--surface-hover', '--sidebar']) {
      for (const text of ['--text', '--text-secondary', '--text-muted', '--accent-text']) {
        expect(contrast(color(text), color(surface)), `${text} on ${surface}`).toBeGreaterThanOrEqual(4.5)
      }
    }
    expect(contrast(color('--on-accent'), color('--accent'))).toBeGreaterThanOrEqual(7)
    expect(contrast(color('--on-accent'), color('--accent-hover'))).toBeGreaterThanOrEqual(7)
    for (const status of ['warning', 'success']) {
      expect(contrast(color(`--${status}-text`), color(`--${status}-soft`))).toBeGreaterThanOrEqual(4.5)
    }
    const [accent] = channels(color('--accent'))
    const [surface] = channels(color('--surface'))
    expect(mode === 'dark' ? accent > surface : accent < surface).toBe(true)
  })
})
