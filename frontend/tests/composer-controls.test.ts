import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { campusUi } from '../src/ui'
import App from '../src/App.vue'
import { useWorkspaceStore } from '../src/store'
import { setLocale } from '../src/i18n'

let dispose = () => {}
let finish = () => {}
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
beforeEach(() => { localStorage.clear(); localStorage.setItem('mens-onboarding-done', '1'); setLocale('zh') })
afterEach(async () => {
  finish(); await flush(); await flush(); dispose(); await flush()
  vi.unstubAllGlobals(); localStorage.clear()
  document.querySelectorAll('.el-popper-container, .el-message').forEach(node => node.remove())
})

async function setup() {
  const requests: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (url.endsWith('/chat/stream')) {
      requests.push(JSON.parse(String(init?.body)))
      return new Response(new ReadableStream({ start(controller) {
        finish = () => {
          controller.enqueue(new TextEncoder().encode('event: done\ndata: {"conversation_id":"fixture-chat","answer":"fixture answer","sources":[]}\n\n'))
          controller.close(); finish = () => {}
        }
      } }))
    }
    if (url.endsWith('/models/config')) return Response.json({ providers: {
      qwen: { configured: true, model: 'qwen-fixture', base_url: '' },
      deepseek: { configured: true, model: 'deepseek-fixture', base_url: '', reasoning: { mode: 'effort', levels: ['low', 'medium', 'high', 'xhigh', 'max'], source: 'configured' } },
      openai_compatible: { configured: false, model: '', base_url: '' },
    }, ollama: { model: 'local-fixture:8b' } })
    if (url.endsWith('/models/local')) return Response.json({ running: true, installed: [{ name: 'local-fixture:8b' }], catalog: [], sources: [] })
    if (url.endsWith('/health')) return Response.json({ status: 'ok', models: {} })
    if (url.endsWith('/web/status')) return Response.json({ enabled: false, available: false, providers: [] })
    return Response.json([])
  })
  const host = document.createElement('div'); document.body.append(host)
  const pinia = createPinia(); const app = createApp(App).use(pinia).use(campusUi)
  app.mount(host); dispose = () => { app.unmount(); host.remove() }
  for (let i = 0; i < 5; i++) await flush()
  return { host, requests, store: useWorkspaceStore(pinia) }
}

async function select(host: HTMLElement, selector: string, label: string) {
  host.querySelector<HTMLElement>(`${selector} .el-select__wrapper`)!.click(); await flush()
  const option = [...document.querySelectorAll<HTMLElement>('.el-select-dropdown__item')].find(node => node.getAttribute('aria-label') === label || node.textContent?.includes(label))!
  expect(option, `option ${label}`).toBeTruthy(); option.click(); await flush()
}

async function send(host: HTMLElement) {
  const input = host.querySelector<HTMLTextAreaElement>('.composer textarea')!
  input.value = 'synthetic question'; input.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
  host.querySelector<HTMLButtonElement>('.composer-send')!.click(); await flush(); await flush()
}

it('shows labeled selectors, sends and saves selected cloud model and reasoning, and locks while generating', async () => {
  const { host, requests, store } = await setup()
  expect(host.querySelector('.composer-preferences label[for="chat-model-select"]')?.textContent).toBe('模型')
  expect(host.querySelector('.composer-preferences label[for="chat-reasoning-select"]')?.textContent).toBe('推理强度')
  await select(host, '.chat-model-picker', 'deepseek-fixture')
  expect(host.querySelector('.chat-model-picker')?.textContent).toContain('DeepSeek · deepseek-fixture')
  await select(host, '.chat-reasoning-picker', '最高')
  await store.flushWorkspace()
  expect(localStorage.getItem('campus-agent-model')).toBe('deepseek')
  expect(localStorage.getItem('campus-agent-reasoning')).toBe('max')
  await send(host)
  expect(requests[0]).toMatchObject({ model: 'deepseek', reasoning: 'max' })
  expect(requests[0]).not.toHaveProperty('local_model')
  for (const selector of ['.chat-model-picker', '.chat-reasoning-picker']) {
    expect(host.querySelector(`${selector} .el-select__wrapper`)?.classList.contains('is-disabled')).toBe(true)
  }
  finish(); await flush(); await flush()
  expect(host.querySelector('.chat-reasoning-picker .is-disabled')).toBeNull()
  expect([...host.querySelectorAll('.message-action')].some(node => node.textContent?.startsWith('以“'))).toBe(false)
})

it('keeps thinking switches separate from effort grades and can restore the default', async () => {
  const { host, requests, store } = await setup()
  await select(host, '.chat-model-picker', 'local-fixture:8b')
  await select(host, '.chat-reasoning-picker', '开启推理')
  expect(store.reasoning).toBe('deep')
  await select(host, '.chat-reasoning-picker', '默认')
  await store.flushWorkspace()
  expect(store.model).toBe('ollama'); expect(store.localModel).toBe('local-fixture:8b')
  expect(localStorage.getItem('campus-agent-reasoning')).toBe('auto')
  await send(host)
  expect(requests[0]).toMatchObject({ model: 'ollama', local_model: 'local-fixture:8b' })
  expect(requests[0]).not.toHaveProperty('reasoning')
})

it('shows default for an unavailable saved grade and never sends a disabled grade after changing models', async () => {
  const { host, requests, store } = await setup()
  await select(host, '.chat-model-picker', 'deepseek-fixture')
  await select(host, '.chat-reasoning-picker', '最高')
  await select(host, '.chat-model-picker', 'qwen-fixture')
  expect(host.querySelector('.chat-reasoning-picker')?.textContent).toContain('默认')
  host.querySelector<HTMLElement>('.chat-reasoning-picker .el-select__wrapper')!.click(); await flush()
  const highest = [...document.querySelectorAll<HTMLElement>('.el-select-dropdown__item')].find(node => node.textContent?.startsWith('最高'))!
  expect(highest.classList.contains('is-disabled')).toBe(true)
  highest.click(); await flush()
  expect(store.reasoning).toBe('max')
  await send(host)
  expect(requests[0].model).toBe('qwen')
  expect(requests[0]).not.toHaveProperty('reasoning')
  finish(); await flush(); await flush()
  await select(host, '.chat-model-picker', 'deepseek-fixture')
  expect(host.querySelector('.chat-reasoning-picker')?.textContent).toContain('最高')
})

it('retries with the next supported grade instead of forcing the legacy deep flag', async () => {
  const { host, requests, store } = await setup()
  await select(host, '.chat-model-picker', 'deepseek-fixture')
  await select(host, '.chat-reasoning-picker', '轻量推理')
  await send(host)
  finish(); await flush(); await flush()
  const retry = [...host.querySelectorAll<HTMLButtonElement>('.message-action')].find(node => node.textContent === '以“中”重试')!
  expect(retry).toBeTruthy(); retry.click(); await flush(); await flush()
  expect(requests[1]).toMatchObject({ reasoning: 'medium', regenerate: true })
  expect(store.reasoning).toBe('medium')
  finish(); await flush(); await flush()
  const next = [...host.querySelectorAll<HTMLButtonElement>('.message-action')].find(node => node.textContent === '以“高”重试')!
  expect(next).toBeTruthy(); next.click(); await flush(); await flush()
  expect(requests[2]).toMatchObject({ reasoning: 'high', regenerate: true })
})

it.each([
  ['zh', '模型', '推理强度', '没有匹配的模型'],
  ['en', 'Model', 'Reasoning effort', 'No matching models'],
  ['ja', 'モデル', '推論の強度', '一致するモデルがありません'],
] as const)('localizes composer labels and empty model searches in %s', async (locale, model, reasoning, empty) => {
  const { host } = await setup(); setLocale(locale); await nextTick()
  expect(host.querySelector('label[for="chat-model-select"]')?.textContent).toBe(model)
  expect(host.querySelector('label[for="chat-reasoning-select"]')?.textContent).toBe(reasoning)
  host.querySelector<HTMLElement>('.chat-model-picker .el-select__wrapper')!.click(); await flush()
  const search = host.querySelector<HTMLInputElement>('#chat-model-select')!
  search.value = 'synthetic-no-matching-model'; search.dispatchEvent(new Event('input', { bubbles: true }))
  await vi.waitFor(() => expect(document.body.textContent).toContain(empty))
})

it('shows project-scoped web read-only permissions without offering an executable write mode', async () => {
  const { host, store } = await setup()
  expect(host.querySelector('label[for="chat-permission-select"]')?.textContent).toBe('项目权限')
  expect(host.querySelector('.chat-permission-picker')?.textContent).toContain('只读')
  expect(host.querySelector('#chat-permission-note')?.textContent).toContain('本机项目')
  host.querySelector<HTMLElement>('.chat-permission-picker .el-select__wrapper')!.click(); await flush()
  const confirm = [...document.querySelectorAll<HTMLElement>('.chat-permission-menu .el-select-dropdown__item')].find(node => node.textContent?.startsWith('修改前确认'))!
  expect(confirm.classList.contains('is-disabled')).toBe(true)
  confirm.click(); await flush(); expect(store.projectPermission).toBe('read_only')
})
