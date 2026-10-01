/**
 * Pure helpers for the interactive hero scene.
 *
 * Kept free of three.js imports so the unit tests (happy-dom, no WebGL) can exercise the
 * capability probes and the pointer maths; the component lazy-loads the renderer itself.
 */

/** Cap the device pixel ratio so high-DPI laptops do not render four times the pixels. */
export const MAX_PIXEL_RATIO = 2
export const PARTICLE_COUNT = 420
export const DRAG_SENSITIVITY = 0.0055
export const WHEEL_SENSITIVITY = 0.0012
export const ZOOM_RANGE: [number, number] = [3.6, 8.2]
export const ROTATION_DAMPING = 0.09

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

export function pixelRatio(devicePixelRatio: number, cap = MAX_PIXEL_RATIO) {
  return clamp(Number.isFinite(devicePixelRatio) ? devicePixelRatio : 1, 1, cap)
}

/** Exponential smoothing used for both rotation inertia and zoom easing. */
export function damp(current: number, target: number, factor = ROTATION_DAMPING) {
  return current + (target - current) * clamp(factor, 0, 1)
}

/** Drag delta (pixels) to rotation delta (radians), clamped to half a turn per frame. */
export function rotationFromDrag(dx: number, dy: number, sensitivity = DRAG_SENSITIVITY) {
  return [
    clamp(dy * sensitivity, -Math.PI / 2, Math.PI / 2),
    clamp(dx * sensitivity, -Math.PI / 2, Math.PI / 2),
  ] as const
}

export function zoomFromWheel(current: number, deltaY: number, sensitivity = WHEEL_SENSITIVITY) {
  return clamp(current + deltaY * sensitivity, ZOOM_RANGE[0], ZOOM_RANGE[1])
}

/** True when the browser can hand out a WebGL context; happy-dom returns false, which is the fallback path. */
export function supportsWebGL(): boolean {
  if (typeof document === 'undefined') return false
  try {
    const probe = document.createElement('canvas')
    return Boolean(probe.getContext('webgl2') || probe.getContext('webgl'))
  } catch {
    return false
  }
}

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/** Resolve a CSS custom property to a usable hex string, with a sensible fallback. */
export function cssColor(variable: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(variable).trim()
  return /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value) ? value : fallback
}

export function currentTheme(): 'light' | 'dark' {
  if (typeof document === 'undefined') return 'light'
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
}
