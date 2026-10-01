import { describe, expect, it } from 'vitest'
import {
  MAX_PIXEL_RATIO, ZOOM_RANGE, clamp, cssColor, currentTheme, damp, pixelRatio,
  prefersReducedMotion, rotationFromDrag, supportsWebGL, zoomFromWheel,
} from '../src/three/sceneKit'

describe('hero scene helpers', () => {
  it('clamps values and caps the pixel ratio', () => {
    expect(clamp(5, 0, 3)).toBe(3)
    expect(clamp(-1, 0, 3)).toBe(0)
    expect(pixelRatio(3.5)).toBe(MAX_PIXEL_RATIO)
    expect(pixelRatio(1.5)).toBe(1.5)
    expect(pixelRatio(Number.NaN)).toBe(1)
  })

  it('smooths towards the target without overshooting', () => {
    let value = 0
    for (let step = 0; step < 200; step += 1) value = damp(value, 1)
    expect(value).toBeGreaterThan(0.99)
    expect(value).toBeLessThanOrEqual(1)
    expect(damp(0, 1, 0)).toBe(0)
    expect(damp(0, 1, 1)).toBe(1)
  })

  it('turns drag pixels into bounded rotation and wheel input into bounded zoom', () => {
    const [x, y] = rotationFromDrag(100, 50)
    expect(y).toBeGreaterThan(0)
    expect(x).toBeGreaterThan(0)
    // A huge flick cannot spin the scene further than a quarter turn per frame.
    expect(Math.abs(rotationFromDrag(100000, 100000)[0])).toBeLessThanOrEqual(Math.PI / 2)
    expect(zoomFromWheel(1, 100000)).toBe(ZOOM_RANGE[1])
    expect(zoomFromWheel(99, -100000)).toBe(ZOOM_RANGE[0])
  })

  it('reports the capability of the current environment', () => {
    // happy-dom has no WebGL and no matchMedia rules, so the component takes its static path.
    expect(typeof supportsWebGL()).toBe('boolean')
    expect(typeof prefersReducedMotion()).toBe('boolean')
  })

  it('falls back for colours and theme when nothing is styled', () => {
    expect(cssColor('--definitely-not-a-token', '#123456')).toBe('#123456')
    expect(['light', 'dark']).toContain(currentTheme())
  })
})
