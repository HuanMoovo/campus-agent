import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, reactive } from 'vue'
import ModelSettings from '../src/components/ModelSettings.vue'
import { api, type ModelConfig } from '../src/api'
import { createModelDraft, diagnosticCapabilities, isModelDraftDirty, modelSavePayload, safeModelEndpoint } from '../src/model-settings'
import { setLocale } from '../src/i18n'

const defaults = { token_parameter: 'max_tokens', send_temperature: true, supports_tools: true, supports_streaming: true, stream_usage: false, max_output_tokens: 900, reasoning_efforts: null }
function config(): ModelConfig {
  return { providers: { qwen: { configured: true, base_url: 'https://example.com/v1', model: 'saved-model' }, deepseek: { configured: false, base_url: 'https://api.deepseek.com', model: 'deepseek-chat' }, openai_compatible: { configured: false, base_url: '', model: '' } }, ollama: { model: 'local-model' } }
}
const cleanup: (() => void)[] = []
function mount(saved = config()) {
  const props = reactive({ config: saved, loadError: '' })
  const host = document.createElement('div')
  document.body.append(host)
  const app = createApp({ render: () => h(ModelSettings, { ...props, 'onUpdate:config': (value: ModelConfig) => { props.config = value } }) })
  app.mount(host)
  cleanup.push(() => { app.unmount(); host.remove() })
  return host
}
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
async function input(host: HTMLElement, selector: string, value: string | boolean) {
  const field = host.querySelector<HTMLInputElement>(selector)!
  if (typeof value === 'boolean') field.checked = value
  else field.value = value
  field.dispatchEvent(new Event(typeof value === 'boolean' ? 'change' : 'input', { bubbles: true }))
  await nextTick()
}
beforeEach(() => setLocale('en'))
afterEach(() => { cleanup.splice(0).forEach(dispose => dispose()); vi.unstubAllGlobals() })

describe('model settings boundaries', () => {
  it('keeps streaming usage opt-in, round-trips it and clears it from native protocols', () => {
    const draft = createModelDraft(config().providers.qwen)
    expect(draft.request_options.stream_usage).toBe(false)
    draft.request_options.stream_usage = true
    expect(modelSavePayload(draft).request_options.stream_usage).toBe(true)
    expect(createModelDraft({ ...config().providers.qwen, request_options: draft.request_options }).request_options.stream_usage).toBe(true)
    draft.protocol = 'anthropic'
    expect(modelSavePayload(draft).request_options.stream_usage).toBe(false)
  })

  it('lets users explicitly request compatible streaming usage and saves that choice', async () => {
    let body: any
    vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => {
      body = JSON.parse(String(init?.body)); return Response.json(config())
    })
    const host = mount()
    expect(host.querySelector('[name="stream_usage"]')).not.toBeNull()
    await input(host, '[name="stream_usage"]', true)
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click()
    await flush()
    expect(body.request_options.stream_usage).toBe(true)
    expect(host.textContent).toContain('stream_options.include_usage')
  })

  it('restores automatic detection and an explicitly disabled reasoning list as different settings', () => {
    const saved = config().providers.qwen
    expect(createModelDraft(saved).request_options.reasoning_efforts).toBeNull()
    for (const efforts of [null, [], ['low', 'max']] as const) {
      const provider = { ...saved, request_options: { ...defaults, reasoning_efforts: efforts === null ? null : [...efforts] } }
      const draft = createModelDraft(provider)
      expect(draft.request_options.reasoning_efforts).toEqual(efforts)
      expect(modelSavePayload(draft).request_options.reasoning_efforts).toEqual(efforts)
      expect(isModelDraftDirty(draft, provider)).toBe(false)
    }
    const draft = createModelDraft(saved)
    draft.request_options.reasoning_efforts = []
    expect(isModelDraftDirty(draft, saved)).toBe(true)
    draft.request_options.reasoning_efforts = null
    expect(isModelDraftDirty(draft, saved)).toBe(false)
  })

  it('clones reasoning lists and preserves a saved automatic choice over catalog defaults', () => {
    const saved = { ...config().providers.qwen, request_options: { ...defaults, reasoning_efforts: ['low', 'high'] as Array<'low' | 'high'> } }
    const draft = createModelDraft(saved)
    draft.request_options.reasoning_efforts!.push('max')
    expect(saved.request_options.reasoning_efforts).toEqual(['low', 'high'])
    expect(isModelDraftDirty(draft, saved)).toBe(true)
    const payload = modelSavePayload(draft)
    draft.request_options.reasoning_efforts!.pop()
    expect(payload.request_options.reasoning_efforts).toEqual(['low', 'high', 'max'])
    const preset = { id: 'qwen' as const, label: 'Qwen', protocol: 'chat_completions' as const, base_url: '', docs_url: '', note: '', request_options: { reasoning_efforts: ['medium'] as Array<'medium'> } }
    expect(createModelDraft(undefined, preset).request_options.reasoning_efforts).toEqual(['medium'])
    expect(createModelDraft({ ...saved, request_options: { ...defaults, reasoning_efforts: null } }, preset).request_options.reasoning_efforts).toBeNull()
  })

  it.each(['anthropic', 'gemini'] as const)('clears reasoning overrides from a %s save payload', protocol => {
    const draft = createModelDraft(config().providers.qwen)
    draft.request_options.reasoning_efforts = ['low', 'max']
    draft.protocol = protocol
    expect(modelSavePayload(draft).request_options.reasoning_efforts).toBeNull()
  })

  it('defaults old configurations and omits a blank API key from a trimmed save', () => {
    const saved = config().providers.qwen
    const draft = createModelDraft(saved)
    expect(draft.request_options).toEqual(defaults)
    draft.base_url = ' https://new.example/v1 '
    draft.model = ' new-model '
    draft.api_key = '  '
    expect(modelSavePayload(draft)).toEqual({ protocol: 'chat_completions', base_url: 'https://new.example/v1', model: 'new-model', request_options: defaults })
    expect(isModelDraftDirty(draft, saved)).toBe(true)
    expect(isModelDraftDirty(createModelDraft(saved), saved)).toBe(false)
  })

  it('only verifies the capability actually probed, including a legacy result', () => {
    expect(diagnosticCapabilities({ ok: true }, 'chat')).toEqual({ chat: 'verified', streaming: 'not_tested', tools: 'not_tested' })
    expect(diagnosticCapabilities({ ok: false, error: 'No call observed' }, 'tools')).toEqual({ chat: 'not_tested', streaming: 'not_tested', tools: 'not_verified' })
    expect(diagnosticCapabilities({ ok: true, capabilities: { chat: 'verified', tools: 'verified', streaming: 'verified' } }, 'streaming')).toEqual({ chat: 'not_tested', streaming: 'verified', tools: 'not_tested' })
    expect(safeModelEndpoint('https://user:secret@example.com/v1?api_key=hidden#secret')).toBe('https://example.com/v1')
  })

  it('uses catalog groups, notes and official links and saves native gateway options independently', async () => {
    const saved = config()
    saved.providers.anthropic = { configured: false, base_url: 'https://api.anthropic.com', model: 'claude-account-model', protocol: 'anthropic' }
    saved.catalog = [
      { id: 'qwen', label: '百炼', protocol: 'chat_completions', base_url: 'https://example.com/v1', docs_url: 'https://example.com/docs', note: 'Choose your regional endpoint.', region: 'china' },
      { id: 'anthropic', label: 'Anthropic', protocol: 'anthropic', base_url: 'https://api.anthropic.com', docs_url: 'https://docs.anthropic.com/en/api', note: 'Use a model enabled for your account.', region: 'global' },
      { id: 'openai_compatible', label: 'Custom gateway', protocol: 'chat_completions', base_url: '', docs_url: '', note: 'Choose the gateway protocol.' },
    ]
    let request: unknown
    let endpoint = ''
    vi.stubGlobal('fetch', async (url: string, init: RequestInit) => { endpoint = url; request = JSON.parse(String(init.body)); return Response.json(saved) })
    const host = mount(saved)
    expect(host.querySelectorAll('.model-provider optgroup')).toHaveLength(3)
    expect(host.textContent).toContain('Choose your regional endpoint.')
    expect(host.querySelector<HTMLAnchorElement>('.model-docs')?.href).toBe('https://example.com/docs')
    expect(host.textContent).toContain('Presets do not verify every model')
    const provider = host.querySelector<HTMLSelectElement>('.model-provider select')!
    provider.value = 'anthropic'; provider.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    expect(host.querySelector<HTMLSelectElement>('[name="protocol"]')?.value).toBe('anthropic')
    expect(host.querySelector('[name="token_parameter"]')).toBeNull()
    await input(host, '[name="max_output_tokens"]', '2048')
    await input(host, '[name="model"]', 'custom-native-model')
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click(); await flush()
    expect(endpoint).toContain('/models/config/anthropic')
    expect(request).toMatchObject({ protocol: 'anthropic', model: 'custom-native-model', request_options: { max_output_tokens: 2048 } })
    provider.value = 'qwen'; provider.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    expect(host.querySelector<HTMLInputElement>('[name="model"]')?.value).toBe('saved-model')
    expect(host.querySelector<HTMLSelectElement>('[name="protocol"]')?.value).toBe('chat_completions')
  })

  it('uses Xiaomi catalog compatibility defaults, preserves explicit overrides and never sends auth header metadata as settings', async () => {
    const saved = config()
    saved.providers.xiaomi = { configured: false, base_url: 'https://api.xiaomimimo.com/v1', model: 'fixture-mimo' }
    saved.catalog = [{ id: 'xiaomi', label: '小米 · MiMo', protocol: 'chat_completions', base_url: 'https://api.xiaomimimo.com/v1', docs_url: '', note: '', region: 'china', auth_header: 'api-key', request_options: { token_parameter: 'max_completion_tokens', send_temperature: false } }]
    const writes: Array<{ url: string; body: unknown }> = []
    vi.stubGlobal('fetch', async (url: string, init: RequestInit) => { writes.push({ url, body: JSON.parse(String(init.body)) }); return Response.json(saved) })
    const host = mount(saved)
    const provider = host.querySelector<HTMLSelectElement>('.model-provider select')!
    provider.value = 'xiaomi'; provider.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    expect(host.querySelector<HTMLSelectElement>('[name="token_parameter"]')!.value).toBe('max_completion_tokens')
    expect(host.querySelector<HTMLInputElement>('[name="send_temperature"]')!.checked).toBe(false)
    expect(host.textContent).not.toContain('Save changes before testing')
    await input(host, '[name="api_key"]', 'fixture-key')
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click(); await flush()
    expect(writes[0]).toMatchObject({ url: '/api/models/config/xiaomi', body: { model: 'fixture-mimo', api_key: 'fixture-key', request_options: { token_parameter: 'max_completion_tokens', send_temperature: false } } })
    expect((writes[0]!.body as Record<string, unknown>).auth_header).toBeUndefined()
    expect(host.querySelector<HTMLSelectElement>('[name="token_parameter"]')!.value).toBe('max_completion_tokens')
    const overridden = createModelDraft({ ...saved.providers.xiaomi, request_options: { ...defaults, token_parameter: 'max_tokens', send_temperature: true } }, saved.catalog[0])
    expect(overridden.request_options).toMatchObject({ token_parameter: 'max_tokens', send_temperature: true })
  })

  it('keeps domestic Zhipu and international Z.AI GLM saves in separate provider slots', async () => {
    const saved = config()
    saved.providers.zhipu = { configured: false, base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'domestic-glm' }
    saved.providers.zai = { configured: false, base_url: 'https://api.z.ai/api/paas/v4', model: 'international-glm' }
    saved.catalog = [
      { id: 'zhipu', label: '智谱 · GLM', protocol: 'chat_completions', base_url: saved.providers.zhipu.base_url, docs_url: '', note: '', region: 'china' },
      { id: 'zai', label: 'Z.AI · GLM', protocol: 'chat_completions', base_url: saved.providers.zai.base_url, docs_url: '', note: '', region: 'global' },
    ]
    const writes: Array<{ url: string; body: unknown }> = []
    vi.stubGlobal('fetch', async (url: string, init: RequestInit) => { writes.push({ url, body: JSON.parse(String(init.body)) }); return Response.json(saved) })
    const host = mount(saved)
    const provider = host.querySelector<HTMLSelectElement>('.model-provider select')!
    for (const [id, model, key] of [['zhipu', 'domestic-glm', 'domestic-key'], ['zai', 'international-glm', 'international-key']]) {
      provider.value = id!; provider.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
      expect(host.querySelector<HTMLInputElement>('[name="model"]')!.value).toBe(model)
      expect(host.querySelector<HTMLInputElement>('[name="api_key"]')!.value).toBe('')
      await input(host, '[name="api_key"]', key!)
      host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click(); await flush()
    }
    expect(writes).toEqual([
      { url: '/api/models/config/zhipu', body: { protocol: 'chat_completions', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'domestic-glm', api_key: 'domestic-key', request_options: defaults } },
      { url: '/api/models/config/zai', body: { protocol: 'chat_completions', base_url: 'https://api.z.ai/api/paas/v4', model: 'international-glm', api_key: 'international-key', request_options: defaults } },
    ])
  })

  it('retains three cloud choices with an old server and rejects invalid output limits', async () => {
    const fetch = vi.fn(async () => Response.json(config()))
    vi.stubGlobal('fetch', fetch)
    const host = mount()
    expect(host.querySelectorAll('.model-provider option')).toHaveLength(3)
    await input(host, '[name="max_output_tokens"]', '63')
    host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); await flush()
    expect(fetch).not.toHaveBeenCalled()
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('64')
  })

  it.each(['responses', 'anthropic', 'gemini'] as const)('saves a custom %s gateway and restores Chat Completions fields when switching back', async protocol => {
    let request: unknown
    let endpoint = ''
    vi.stubGlobal('fetch', async (url: string, init: RequestInit) => { endpoint = url; request = JSON.parse(String(init.body)); return Response.json(config()) })
    const host = mount()
    const provider = host.querySelector<HTMLSelectElement>('.model-provider select')!
    provider.value = 'openai_compatible'; provider.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    const select = host.querySelector<HTMLSelectElement>('[name="protocol"]')!
    select.value = protocol; select.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    expect(host.querySelector('[name="token_parameter"]')).toBeNull()
    await input(host, '[name="base_url"]', 'https://custom.example/native')
    await input(host, '[name="api_key"]', ' gateway-key ')
    await input(host, '[name="model"]', 'account-model')
    await input(host, '[name="max_output_tokens"]', '4096')
    await input(host, '[name="supports_streaming"]', false)
    await input(host, '[name="supports_tools"]', false)
    await input(host, '[name="send_temperature"]', false)
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click(); await flush()
    expect(endpoint).toContain('/models/config/openai_compatible')
    expect(request).toEqual({ protocol, base_url: 'https://custom.example/native', api_key: 'gateway-key', model: 'account-model', request_options: { token_parameter: 'max_tokens', max_output_tokens: 4096, send_temperature: false, supports_streaming: false, stream_usage: false, supports_tools: false, reasoning_efforts: null } })
    select.value = 'chat_completions'; select.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    expect(host.querySelector('[name="token_parameter"]')).not.toBeNull()
  })

  it('sends the requested capability to the diagnostic endpoint and accepts an old response', async () => {
    let body: unknown
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => { body = JSON.parse(String(init.body)); return Response.json({ ok: true }) })
    await expect(api.testModel('qwen', 'tools')).resolves.toEqual({ ok: true })
    expect(body).toEqual({ capability: 'tools' })
    await api.testModel('qwen')
    expect(body).toEqual({ capability: 'chat' })
  })

  it.each(['chat_completions', 'responses'] as const)('saves a declared reasoning subset through %s without claiming verification', async protocol => {
    const saved = config()
    saved.providers.qwen.protocol = protocol
    let request: unknown
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => { request = JSON.parse(String(init.body)); return Response.json(saved) })
    const host = mount(saved)
    const mode = host.querySelector<HTMLSelectElement>('[name="reasoning_support"]')!
    expect(mode?.value).toBe('auto')
    mode.value = 'manual'; mode.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    expect(host.querySelectorAll('[name="reasoning_efforts"]')).toHaveLength(5)
    await input(host, '[name="reasoning_efforts"][value="low"]', true)
    await input(host, '[name="reasoning_efforts"][value="max"]', true)
    expect(host.querySelector<HTMLButtonElement>('[data-probe="chat"]')?.disabled).toBe(true)
    expect(host.querySelector('[role="status"]')).toBeNull()
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click(); await flush()
    expect(request).toMatchObject({ protocol, request_options: { reasoning_efforts: ['low', 'max'] } })
    expect(host.querySelector('[role="status"]')).toBeNull()
  })

  it('requires a manual reasoning selection and can explicitly disable reasoning parameters', async () => {
    const writes: unknown[] = []
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => { writes.push(JSON.parse(String(init.body))); return Response.json(config()) })
    const host = mount()
    const mode = host.querySelector<HTMLSelectElement>('[name="reasoning_support"]')!
    mode.value = 'manual'; mode.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click(); await flush()
    expect(writes).toEqual([])
    expect(host.querySelector('[role="alert"]')).not.toBeNull()
    mode.value = 'disabled'; mode.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    expect(host.querySelector('[name="reasoning_efforts"]')).toBeNull()
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click(); await flush()
    expect(writes).toEqual([{ protocol: 'chat_completions', base_url: 'https://example.com/v1', model: 'saved-model', request_options: { ...defaults, reasoning_efforts: [] } }])
  })

  it('restores a saved reasoning subset when changing providers and saves automatic mode as null', async () => {
    const saved = config()
    saved.providers.qwen.request_options = { ...defaults, reasoning_efforts: ['medium', 'xhigh'] }
    saved.providers.deepseek.request_options = { ...defaults, reasoning_efforts: [] }
    let request: unknown
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => { request = JSON.parse(String(init.body)); return Response.json(saved) })
    const host = mount(saved)
    expect(host.querySelector<HTMLSelectElement>('[name="reasoning_support"]')?.value).toBe('manual')
    expect(Array.from(host.querySelectorAll<HTMLInputElement>('[name="reasoning_efforts"]:checked')).map(field => field.value)).toEqual(['medium', 'xhigh'])
    const provider = host.querySelector<HTMLSelectElement>('.model-provider select')!
    provider.value = 'deepseek'; provider.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    expect(host.querySelector<HTMLSelectElement>('[name="reasoning_support"]')?.value).toBe('disabled')
    provider.value = 'qwen'; provider.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    expect(Array.from(host.querySelectorAll<HTMLInputElement>('[name="reasoning_efforts"]:checked')).map(field => field.value)).toEqual(['medium', 'xhigh'])
    const mode = host.querySelector<HTMLSelectElement>('[name="reasoning_support"]')!
    mode.value = 'auto'; mode.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click(); await flush()
    expect(request).toMatchObject({ request_options: { reasoning_efforts: null } })
  })

  it.each(['anthropic', 'gemini'] as const)('hides reasoning choices and removes overrides when switching to %s', async protocol => {
    const saved = config()
    saved.providers.qwen.request_options = { ...defaults, reasoning_efforts: ['low', 'max'] }
    let request: unknown
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => { request = JSON.parse(String(init.body)); return Response.json(saved) })
    const host = mount(saved)
    const select = host.querySelector<HTMLSelectElement>('[name="protocol"]')!
    select.value = protocol; select.dispatchEvent(new Event('change', { bubbles: true })); await nextTick()
    expect(host.querySelector('[name="reasoning_support"]')).toBeNull()
    expect(host.querySelector('[name="reasoning_efforts"]')).toBeNull()
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click(); await flush()
    expect(request).toMatchObject({ protocol, request_options: { reasoning_efforts: null } })
  })

  it('disables saved configuration probes for a draft and saves compatibility choices', async () => {
    let request: unknown
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => { request = JSON.parse(String(init.body)); const saved = config(); saved.providers.qwen.model = 'new-model'; return Response.json(saved) })
    const host = mount()
    expect(host.querySelector<HTMLDetailsElement>('details')?.open).toBe(false)
    expect(host.querySelector<HTMLButtonElement>('[data-probe="chat"]')?.disabled).toBe(false)
    await input(host, '[name="model"]', 'new-model')
    await input(host, '[name="supports_tools"]', false)
    expect(host.querySelector<HTMLButtonElement>('[data-probe="chat"]')?.disabled).toBe(true)
    expect(host.textContent).toContain('Save changes before testing')
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click()
    await flush()
    expect(request).toEqual({ protocol: 'chat_completions', base_url: 'https://example.com/v1', model: 'new-model', request_options: { ...defaults, supports_tools: false } })
    expect(host.querySelector<HTMLInputElement>('[name="api_key"]')!.value).toBe('')
  })

  it('clears only the key even while a different model and endpoint are unsaved', async () => {
    let request: unknown
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => { request = JSON.parse(String(init.body)); return Response.json(config()) })
    const host = mount()
    await input(host, '[name="model"]', 'unsaved-model')
    await input(host, '[name="base_url"]', 'https://another.example/v1')
    await input(host, '[name="api_key"]', 'new-secret')
    host.querySelector<HTMLButtonElement>('[data-action="clear"]')!.click()
    await flush()
    expect(request).toEqual({ clear_api_key: true })
    expect(host.textContent).not.toContain('new-secret')
    expect(host.querySelector<HTMLInputElement>('[name="api_key"]')!.value).toBe('')
    expect(host.querySelector<HTMLInputElement>('[name="model"]')!.value).toBe('unsaved-model')
  })

  it.each(['https://another.example/v1', 'https://example.com:8443/v1'])('requires a replacement or cleared key before saving authority change to %s', async endpoint => {
    const fetch = vi.fn(async () => Response.json(config()))
    vi.stubGlobal('fetch', fetch)
    const saved = config()
    saved.providers.qwen.api_key_set = true
    saved.providers.qwen.configured = false
    const host = mount(saved)
    await input(host, '[name="base_url"]', endpoint)
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click()
    await flush()
    expect(fetch).not.toHaveBeenCalled()
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Enter a new API key or clear the saved key')
    expect(host.querySelector<HTMLButtonElement>('[data-action="clear"]')?.disabled).toBe(false)
    host.querySelector<HTMLButtonElement>('[data-action="clear"]')!.click()
    await flush()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({ clear_api_key: true })
    expect(host.querySelector<HTMLInputElement>('[name="base_url"]')?.value).toBe(endpoint)
  })

  it.each([
    { endpoint: 'https://EXAMPLE.COM:443/v2', key: '' },
    { endpoint: 'https://another.example/v1', key: ' replacement-key ' },
  ])('allows a matching effective authority or replacement key: $endpoint', async ({ endpoint, key }) => {
    let request: unknown
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => { request = JSON.parse(String(init.body)); return Response.json(config()) })
    const host = mount()
    await input(host, '[name="base_url"]', endpoint)
    await input(host, '[name="api_key"]', key)
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click()
    await flush()
    expect(request).toEqual({ protocol: 'chat_completions', base_url: endpoint, model: 'saved-model', request_options: defaults, ...(key ? { api_key: 'replacement-key' } : {}) })
    expect(host.querySelector('[role="alert"]')).toBeNull()
  })

  it('keeps provider selection and draft fields disabled while a save is pending', async () => {
    let finish!: (value: Response) => void
    vi.stubGlobal('fetch', () => new Promise<Response>(resolve => { finish = resolve }))
    const host = mount()
    host.querySelector<HTMLButtonElement>('[data-action="save"]')!.click()
    await nextTick()
    expect(host.querySelector<HTMLSelectElement>('.model-provider select')?.disabled).toBe(true)
    expect(host.querySelector('[name="model"]')?.closest<HTMLFieldSetElement>('fieldset')?.disabled).toBe(true)
    expect(host.querySelector<HTMLButtonElement>('[data-probe="chat"]')?.disabled).toBe(true)
    finish(Response.json(config()))
    await flush()
    expect(host.querySelector<HTMLSelectElement>('.model-provider select')?.disabled).toBe(false)
    expect(host.querySelector('[name="model"]')?.closest<HTMLFieldSetElement>('fieldset')?.disabled).toBe(false)
  })

  it('retains diagnostic metadata, latency, code and hint without claiming other capabilities', async () => {
    vi.stubGlobal('fetch', async () => Response.json({ ok: false, error: 'No tool call observed.', error_code: 'tool_not_observed', latency_ms: 321, provider: 'qwen', model: 'actually-tested-model', protocol: 'chat_completions', capability: 'tools', capabilities: { chat: 'not_tested', tools: 'not_verified', streaming: 'not_tested' }, hint: 'Try a model with tool calling.' }))
    const host = mount()
    host.querySelector<HTMLButtonElement>('[data-probe="tools"]')!.click()
    await flush()
    const result = host.querySelector('[role="status"]')!
    expect(result.textContent).toContain('actually-tested-model')
    expect(result.textContent).toContain('321 ms')
    expect(result.textContent).toContain('tool_not_observed')
    expect(result.textContent).toContain('Try a model with tool calling.')
    expect(result.querySelector('[data-capability="tools"]')?.textContent).toContain('Not verified')
    expect(result.querySelector('[data-capability="chat"]')?.textContent).toContain('Not tested')
    await input(host, '[name="model"]', 'new-draft')
    expect(host.querySelector('[role="status"]')?.textContent).toContain('actually-tested-model')
  })

  it('blocks disabled probes and uses api_key_set independently of model readiness', () => {
    const saved = config()
    saved.providers.qwen = { ...saved.providers.qwen, configured: false, api_key_set: true, request_options: { ...defaults, token_parameter: 'max_tokens', supports_tools: false, supports_streaming: false } }
    const host = mount(saved)
    expect(host.querySelector<HTMLButtonElement>('[data-action="clear"]')?.disabled).toBe(false)
    expect(host.querySelector<HTMLButtonElement>('[data-probe="tools"]')?.disabled).toBe(true)
    expect(host.querySelector<HTMLButtonElement>('[data-probe="streaming"]')?.disabled).toBe(true)
    const ready = config()
    ready.providers.qwen.request_options = { ...defaults, token_parameter: 'max_tokens', supports_tools: false, supports_streaming: false }
    const readyHost = mount(ready)
    expect(readyHost.querySelector<HTMLButtonElement>('[data-probe="chat"]')?.disabled).toBe(false)
    expect(readyHost.querySelector<HTMLButtonElement>('[data-probe="tools"]')?.disabled).toBe(true)
    expect(readyHost.querySelector<HTMLButtonElement>('[data-probe="streaming"]')?.disabled).toBe(true)
  })

  it('does not label an HTTP failure as a provider connection diagnosis or expose raw errors', async () => {
    vi.stubGlobal('fetch', async () => Response.json({ detail: 'raw-secret-provider-body' }, { status: 400 }))
    const host = mount()
    host.querySelector<HTMLButtonElement>('[data-probe="chat"]')!.click()
    await flush()
    expect(host.querySelector('[role="status"]')?.textContent).toContain('Could not complete the test')
    expect(host.textContent).not.toContain('raw-secret-provider-body')
    expect(host.querySelector('.model-error-code')).toBeNull()
  })

  it('shows only the probed capability as verified for a successful old response', async () => {
    vi.stubGlobal('fetch', async () => Response.json({ ok: true }))
    const host = mount()
    host.querySelector<HTMLButtonElement>('[data-probe="chat"]')!.click()
    await flush()
    expect(host.querySelector('[data-capability="chat"]')?.textContent).toContain('Verified')
    expect(host.querySelector('[data-capability="tools"]')?.textContent).toContain('Not tested')
    expect(host.querySelector('[role="status"]')?.textContent).toContain('saved-model')
    setLocale('ja')
    await nextTick()
    expect(host.querySelector('[data-action="save"]')?.textContent).toBe('設定を保存')
  })
})
