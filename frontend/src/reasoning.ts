import type { ModelConfig } from './api'
import { isCloudModelProvider, modelForApi } from './model-providers'

export const REASONING_LEVELS = ['low', 'medium', 'high', 'xhigh', 'max'] as const
export type ReasoningLevel = typeof REASONING_LEVELS[number]
// deep is retained only for legacy preferences and interfaces with a thinking switch.
export type ReasoningPreference = 'auto' | ReasoningLevel | 'deep'
export interface ReasoningCapability {
  mode: 'effort' | 'toggle' | 'unknown' | 'unsupported'
  levels: ReasoningLevel[]
  source?: 'model' | 'configured'
}

export function isReasoningLevel(value: unknown): value is ReasoningLevel {
  return typeof value === 'string' && (REASONING_LEVELS as readonly string[]).includes(value)
}
export function normalizeReasoning(value: unknown): ReasoningPreference {
  return value === 'deep' || isReasoningLevel(value) ? value : 'auto'
}
export function reasoningForModel(model: string, config: ModelConfig | null): ReasoningCapability {
  if (model === 'ollama' || model.startsWith('local:')) return { mode: 'toggle', levels: [] }
  const id = modelForApi(model)
  const capability = isCloudModelProvider(id) ? config?.providers[id]?.reasoning : undefined
  if (!capability || !['effort', 'toggle', 'unknown', 'unsupported'].includes(capability.mode)) return { mode: 'unknown', levels: [] }
  return { ...capability, levels: REASONING_LEVELS.filter(level => capability.levels?.includes(level)) }
}
export function effectiveReasoning(value: ReasoningPreference, capability: ReasoningCapability): ReasoningPreference {
  if (value === 'deep') {
    if (capability.mode === 'toggle') return 'deep'
    return capability.mode === 'effort' && capability.levels.includes('high') ? 'high' : 'auto'
  }
  return isReasoningLevel(value) && capability.mode === 'effort' && capability.levels.includes(value) ? value : 'auto'
}
export function nextReasoning(value: ReasoningPreference, capability: ReasoningCapability): ReasoningPreference | null {
  const current = effectiveReasoning(value, capability)
  if (capability.mode === 'toggle') return current === 'deep' ? null : 'deep'
  if (capability.mode !== 'effort') return null
  const levels = REASONING_LEVELS.filter(level => capability.levels.includes(level))
  if (current === 'auto') return levels.includes('high') ? 'high' : levels.at(-1) || null
  return levels[levels.indexOf(current as ReasoningLevel) + 1] || null
}
