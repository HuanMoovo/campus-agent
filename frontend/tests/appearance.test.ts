import { describe, expect, it } from 'vitest'

import { applyAppearance, DEFAULT_ACCENT, normalizeAccent } from '../src/appearance'

describe('appearance', () => {
  it('normalizes hex colours and rejects everything else', () => {
    expect(normalizeAccent('#A1B2C3')).toBe('#a1b2c3')
    expect(normalizeAccent('  #00ff00 ')).toBe('#00ff00')
    for (const value of ['red', '#fff', '#12345', '', null, 12, '#12345g']) {
      expect(normalizeAccent(value)).toBeNull()
    }
  })

  it('switches theme attributes and falls back to the default accent', () => {
    applyAppearance('dark', 'not-a-colour', false)
    const root = document.documentElement
    expect(root.dataset.theme).toBe('dark')
    expect(root.style.getPropertyValue('--accent')).toBe(DEFAULT_ACCENT)
    applyAppearance('system', DEFAULT_ACCENT, false)
    expect(root.dataset.theme).toBe('light')
    applyAppearance('system', DEFAULT_ACCENT, true)
    expect(root.dataset.theme).toBe('dark')
    applyAppearance('light', DEFAULT_ACCENT, true)
    expect(root.dataset.theme).toBe('light')
  })

  it('derives readable accent variables from a custom colour', () => {
    applyAppearance('light', '#b03a2e', false)
    const style = document.documentElement.style
    expect(style.getPropertyValue('--accent')).toBe('#b03a2e')
    // Already readable on the light surface, so the text colour stays the accent itself.
    expect(style.getPropertyValue('--accent-text')).toBe('#b03a2e')
    expect(style.getPropertyValue('--on-accent')).toMatch(/^#(ffffff|000000)$/)
    // A pale accent must be darkened before it can carry text.
    applyAppearance('light', '#f7d94c', false)
    expect(style.getPropertyValue('--accent-text')).not.toBe('#f7d94c')
    expect(style.getPropertyValue('--accent-text')).toMatch(/^#[0-9a-f]{6}$/)
  })
})
