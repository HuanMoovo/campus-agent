import { afterEach, expect, it, vi } from 'vitest'
import { chatStream, type ModelConfig } from '../src/api'
import { effectiveReasoning, nextReasoning, normalizeReasoning, reasoningForModel, REASONING_LEVELS, type ReasoningCapability } from '../src/reasoning'

const effort: ReasoningCapability = { mode: 'effort', levels: [...REASONING_LEVELS] }
afterEach(() => vi.unstubAllGlobals())

it('uses only the selected provider capability and keeps legacy thinking switches separate', () => {
  const config = { providers: { qwen: { reasoning: effort } } } as unknown as ModelConfig
  expect(reasoningForModel('qwen3', config)).toEqual(effort)
  expect(reasoningForModel('auto', config)).toEqual({ mode: 'unknown', levels: [] })
  expect(reasoningForModel('anthropic', config)).toEqual({ mode: 'unknown', levels: [] })
  expect(reasoningForModel('local:fixture', config)).toEqual({ mode: 'toggle', levels: [] })
  expect(normalizeReasoning('fast')).toBe('auto')
  expect(effectiveReasoning('deep', effort)).toBe('high')
  expect(effectiveReasoning('deep', { mode: 'toggle', levels: [] })).toBe('deep')
  expect(effectiveReasoning('high', { mode: 'toggle', levels: [] })).toBe('auto')
  expect(effectiveReasoning('max', { mode: 'effort', levels: ['low', 'high'] })).toBe('auto')
})

it('only offers a supported stronger retry and stops at the highest available grade', () => {
  expect(nextReasoning('auto', effort)).toBe('high')
  expect(nextReasoning('low', effort)).toBe('medium')
  expect(nextReasoning('xhigh', effort)).toBe('max')
  expect(nextReasoning('max', effort)).toBeNull()
  expect(nextReasoning('low', { mode: 'effort', levels: ['low', 'max'] })).toBe('max')
  expect(nextReasoning('auto', { mode: 'unknown', levels: [] })).toBeNull()
  expect(nextReasoning('deep', { mode: 'toggle', levels: [] })).toBeNull()
})

it.each(['auto', ...REASONING_LEVELS] as const)('serializes the actual %s effort without collapsing grades into deep', async reasoning => {
  let request: Record<string, unknown> = {}
  vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => {
    request = JSON.parse(String(init?.body))
    return new Response('event: done\ndata: {"answer":"fixture","sources":[]}\n\n')
  })
  await chatStream({ message: 'synthetic', model: 'openai_responses', conversationId: '', clientId: 'fixture', reasoning }, {}, new AbortController().signal)
  expect(request.model).toBe('openai_responses')
  if (reasoning === 'auto') expect(request).not.toHaveProperty('reasoning')
  else expect(request.reasoning).toBe(reasoning)
})
