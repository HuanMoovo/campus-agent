import { afterEach, describe, expect, it, vi } from 'vitest'
import { chatStream, type ModelConfig } from '../src/api'
import { CLOUD_MODEL_IDS, isWorkspaceModel, modelCatalog, officialDocsUrl, providerGroups, workspaceModelForProvider } from '../src/model-providers'

afterEach(() => vi.unstubAllGlobals())

describe('cloud model selection contract', () => {
  it('accepts the expanded Xiaomi and international catalog while excluding retired presets', () => {
    for (const id of ['xiaomi', 'zai', 'xai', 'openrouter', 'groq', 'mistral', 'together', 'fireworks', 'deepinfra', 'cerebras', 'huggingface', 'cohere']) {
      expect(CLOUD_MODEL_IDS).toContain(id)
      expect(isWorkspaceModel(id)).toBe(true)
    }
    expect(CLOUD_MODEL_IDS).not.toContain('github_models')
    expect(CLOUD_MODEL_IDS).not.toContain('perplexity')
  })
  it.each(CLOUD_MODEL_IDS)('sends selected %s unchanged apart from the legacy Qwen workspace alias', async id => {
    let body: Record<string, unknown> = {}
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => {
      body = JSON.parse(String(init.body))
      return new Response(`event: done\ndata: ${JSON.stringify({ answer: 'Saved selection works', sources: [] })}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
    })
    const model = workspaceModelForProvider(id)
    expect(isWorkspaceModel(model)).toBe(true)
    if (id === 'qwen') expect(model).toBe('qwen3')
    await expect(chatStream({ message: 'Test', conversationId: '', model, clientId: 'selection-test' }, {}, new AbortController().signal)).resolves.toMatchObject({ answer: 'Saved selection works' })
    expect(body.model).toBe(id)
  })

  it('honors the server catalog and ignores unknown or duplicate provider IDs', () => {
    const catalog: ModelConfig['catalog'] = CLOUD_MODEL_IDS.map(id => ({ id, label: `Account ${id}`, protocol: 'chat_completions', base_url: '', docs_url: '', note: '', region: id === 'openai_compatible' ? undefined : ['anthropic', 'gemini', 'openai_responses', 'zai', 'xai', 'openrouter', 'groq', 'mistral', 'together', 'fireworks', 'deepinfra', 'cerebras', 'huggingface', 'cohere'].includes(id) ? 'global' : 'china' }))
    const config = { providers: {}, catalog: [...catalog, catalog[0], { ...catalog[0], id: 'unsupported-server-id' }], ollama: { model: '' } } as ModelConfig
    expect(modelCatalog(config)).toHaveLength(28)
    expect(providerGroups(config).map(group => [group.id, group.entries.length])).toEqual([['china', 13], ['global', 14], ['custom', 1]])
    expect(modelCatalog(config)[3]?.label).toBe('Account openai_responses')
    expect(modelCatalog()).toHaveLength(3)
    expect(isWorkspaceModel('untrusted')).toBe(false)
    expect(isWorkspaceModel('qwen')).toBe(false)
  })

  it('shows only credential-free HTTPS official document links', () => {
    const entry = { id: 'gemini', label: 'Gemini', protocol: 'gemini', base_url: '', docs_url: '', note: '' } as const
    expect(officialDocsUrl({ ...entry, docs_url: 'https://ai.google.dev/gemini-api/docs' })).toBe('https://ai.google.dev/gemini-api/docs')
    for (const docs_url of ['javascript:alert(1)', 'http://example.com', 'https://secret:key@example.com']) expect(officialDocsUrl({ ...entry, docs_url })).toBe('')
  })
})
