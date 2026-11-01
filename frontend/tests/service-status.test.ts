import { describe, expect, it } from 'vitest'
import { serviceResultStatus } from '../src/service-status'

describe('campus service results', () => {
  it('distinguishes unconfigured extended services from an empty school response', () => {
    expect(serviceResultStatus('notices', { demo: true, items: [] })).toBe('unconfigured')
    expect(serviceResultStatus('notices', { demo: false, items: [] })).toBe('connected')
  })
  it('keeps core demo responses and unknown sources honest', () => {
    expect(serviceResultStatus('schedule', { demo: true, items: [] })).toBe('demo')
    expect(serviceResultStatus('schedule', { items: [] })).toBe('unknown')
    expect(serviceResultStatus('repair', { demo: true, id: 'demo-1' })).toBe('demo')
  })
})
