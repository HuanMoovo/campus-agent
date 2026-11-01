import { afterEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import App from '../src/App.vue'
import { useWorkspaceStore } from '../src/store'
import { CLOUD_MODEL_IDS, workspaceModelForProvider } from '../src/model-providers'
import type { ModelConfig } from '../src/api'

let dispose = () => {}
afterEach(() => { dispose(); vi.unstubAllGlobals(); localStorage.clear(); document.querySelectorAll('.el-popper-container').forEach(node => node.remove()) })

async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
const newProviderIds = ['xiaomi', 'zai', 'xai', 'openrouter', 'groq', 'mistral', 'together', 'fireworks', 'deepinfra', 'cerebras', 'huggingface', 'cohere'] as const
const providerLabel = (id: string) => id === 'xiaomi' ? '小米 · MiMo' : id === 'zai' ? 'Z.AI · GLM' : id === 'zhipu' ? '智谱 · GLM' : `Provider ${id}`

async function mountCatalogApp() {
  localStorage.clear()
  localStorage.setItem('mens-onboarding-done', '1')
  const providers = Object.fromEntries(CLOUD_MODEL_IDS.map(id => [id, { configured: false, base_url: '', model: '' }])) as ModelConfig['providers']
  const catalog: ModelConfig['catalog'] = CLOUD_MODEL_IDS.map(id => ({ id, label: providerLabel(id), protocol: id === 'anthropic' || id === 'gemini' ? id : id === 'openai_responses' ? 'responses' : 'chat_completions', base_url: '', docs_url: '', note: '', region: id === 'openai_compatible' ? undefined : ['anthropic', 'gemini', 'openai_responses', ...newProviderIds.filter(value => value !== 'xiaomi')].includes(id) ? 'global' : 'china' }))
  vi.stubGlobal('fetch', async (url: string) => {
    if (url.endsWith('/models/config')) return Response.json({ providers, catalog, ollama: { model: '' } })
    if (url.endsWith('/models/local')) return Response.json({ running: false, installed: [], catalog: [], sources: [] })
    if (url.endsWith('/web/status')) return Response.json({ enabled: false, available: false, providers: [] })
    if (url.endsWith('/health')) return Response.json({ status: 'ok', models: { yi: false, anthropic: false } })
    return Response.json([])
  })
  const host = document.createElement('div')
  document.body.append(host)
  const pinia = createPinia()
  const app = createApp(App).use(pinia).use(ElementPlus)
  dispose = () => { app.unmount(); host.remove() }
  app.mount(host)
  await flush(); await flush()
  return { host, store: useWorkspaceStore(pinia) }
}

it('lists the complete server catalog and persists initial China and native provider choices', async () => {
  const { host, store } = await mountCatalogApp()
  host.querySelector<HTMLElement>('.chat-model-picker .el-select__wrapper')!.click()
  await flush()
  for (const id of CLOUD_MODEL_IDS.filter(id => id !== 'openai_compatible')) {
    expect(document.body.textContent).toContain(providerLabel(id))
  }
  const yi = [...document.querySelectorAll<HTMLElement>('.el-select-dropdown__item')].find(node => node.textContent === 'Provider yi')!
  yi.click(); await flush()
  expect(store.model).toBe('yi')
  await store.flushWorkspace()
  expect(localStorage.getItem('campus-agent-model')).toBe('yi')
  store.view = 'settings'
  await flush(); await flush()
  expect(host.querySelector('.settings-model-picker')).not.toBeNull()
  expect(host.querySelector('.settings-section .el-radio-group')).toBeNull()
  host.querySelector<HTMLElement>('.settings-model-picker .el-select__wrapper')!.click(); await flush()
  const anthropic = [...document.querySelectorAll<HTMLElement>('.el-select-dropdown__item')].find(node => node.textContent === 'Provider anthropic')!
  anthropic.click(); await flush()
  expect(store.model).toBe(workspaceModelForProvider('anthropic'))
  await store.flushWorkspace()
  expect(localStorage.getItem('campus-agent-model')).toBe('anthropic')
})

const selectorCases = ([['chat', '.chat-model-picker'], ['settings', '.settings-model-picker']] as const)
  .flatMap(([view, selector]) => [...newProviderIds, 'zhipu' as const].map(id => ({ view, selector, id })))

it.each(selectorCases)('selects $id in $view and persists the choice', async ({ view, selector, id }) => {
  const { host, store } = await mountCatalogApp()
  store.view = view; await flush(); await flush()
  host.querySelector<HTMLElement>(`${selector} .el-select__wrapper`)!.click(); await flush()
  const item = [...document.querySelectorAll<HTMLElement>('.el-select-dropdown__item')].find(node => node.textContent === providerLabel(id))!
  expect(item, `${id} is selectable in ${view}`).toBeTruthy()
  item.click(); await flush()
  expect(store.model).toBe(id)
  await store.flushWorkspace()
  expect(localStorage.getItem('campus-agent-model')).toBe(id)
})
