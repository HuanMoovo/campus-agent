import { afterEach, expect, it, vi } from 'vitest'
import { createApp, defineComponent, h, nextTick, ref } from 'vue'
import { createPinia } from 'pinia'
import SettingsShell from '../src/components/SettingsShell.vue'
import App from '../src/App.vue'
import { campusUi } from '../src/ui'
import { useWorkspaceStore } from '../src/store'
import { setLocale } from '../src/i18n'

let dispose = () => {}
afterEach(() => { dispose(); vi.unstubAllGlobals(); localStorage.clear(); document.querySelectorAll('.el-popper-container').forEach(node => node.remove()) })
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }

it('keeps form identity and unsaved values while native settings navigation changes', async () => {
  setLocale('zh')
  const category = ref('general')
  const host = document.createElement('div'); document.body.append(host)
  const root = defineComponent(() => () => h(SettingsShell, {
    modelValue: category.value,
    'onUpdate:modelValue': (value: string) => { category.value = value },
  }, { general: () => h('p', 'appearance'), models: () => h('input', { name: 'draft' }) }))
  const app = createApp(root); app.mount(host)
  dispose = () => { app.unmount(); host.remove() }
  const modelButton = host.querySelector<HTMLButtonElement>('[data-settings-target="models"]')!
  expect(modelButton.tagName).toBe('BUTTON')
  modelButton.click(); await nextTick()
  const input = host.querySelector<HTMLInputElement>('[name="draft"]')!
  input.value = 'unsaved-secret-fixture'
  host.querySelector<HTMLButtonElement>('[data-settings-target="general"]')!.click(); await nextTick()
  expect(host.querySelector<HTMLElement>('[data-settings-section="models"]')!.style.display).toBe('none')
  modelButton.click(); await nextTick()
  expect(host.querySelector('[name="draft"]')).toBe(input)
  expect(input.value).toBe('unsaved-secret-fixture')
  expect(modelButton.getAttribute('aria-current')).toBe('page')
  expect(host.querySelectorAll('[aria-current="page"]')).toHaveLength(1)
})

it('groups the actual settings, retains a model draft and fetches usage only on entry', async () => {
  setLocale('zh'); localStorage.setItem('mens-onboarding-done', '1')
  let usageCalls = 0
  let campusCalls = 0
  let webCalls = 0
  vi.stubGlobal('fetch', async (value: string) => {
    const url = String(value)
    if (url.includes('/usage?')) { usageCalls++; return Response.json({ days: 7, timezone: 'UTC', start_date: '2026-10-25', end_date: '2026-10-31', totals: { requests: 0, reported_requests: 0, partial_requests: 0, unreported_requests: 0, input_tokens: null, output_tokens: null, total_tokens: null, cached_input_tokens: null, cache_creation_input_tokens: null, reasoning_tokens: null }, daily: [], models: [] }) }
    if (url.endsWith('/health')) return Response.json({ status: 'ok', models: {} })
    if (url.endsWith('/models/config')) return Response.json({ providers: { qwen: { configured: true, model: 'fixture', base_url: 'https://example.test/v1' } }, ollama: { model: '' } })
    if (url.endsWith('/models/local')) return Response.json({ running: false, installed: [], catalog: [], sources: [] })
    if (url.endsWith('/campus-sources')) { campusCalls++; return Response.json([]) }
    if (url.endsWith('/web/status')) { webCalls++; return Response.json({ enabled: false, available: false, provider: 'bing', max_results: 5, fetch_pages: 2, providers: [] }) }
    return Response.json([])
  })
  const host = document.createElement('div'); document.body.append(host)
  const pinia = createPinia(); const app = createApp(App).use(pinia).use(campusUi)
  app.mount(host); dispose = () => { app.unmount(); host.remove() }
  for (let index = 0; index < 4; index++) await flush()
  const store = useWorkspaceStore(pinia)
  store.view = 'settings'; await flush()
  expect(host.querySelectorAll('.settings-nav button')).toHaveLength(5)
  expect(usageCalls).toBe(0)
  host.querySelector<HTMLButtonElement>('[data-settings-target="models"]')!.click(); await flush()
  const draft = host.querySelector<HTMLInputElement>('[name="api_key"]')!
  draft.value = 'fixture-unsaved'; draft.dispatchEvent(new Event('input', { bubbles: true }))
  host.querySelector<HTMLButtonElement>('[data-settings-target="connections"]')!.click(); await flush()
  expect(host.querySelector<HTMLElement>('[data-settings-section="models"]')!.style.display).toBe('none')
  expect(host.querySelector<HTMLElement>('[data-settings-section="connections"]')!.style.display).not.toBe('none')
  const campusUrl = host.querySelector<HTMLInputElement>('#campus-source-settings input[placeholder="https://school.edu/api/grades"]')!
  const webKey = host.querySelector<HTMLInputElement>('.web-form input[type="password"]')!
  for (const [field, value] of [[campusUrl, 'https://draft.example.test/grades'], [webKey, 'fixture-search-key']] as const) {
    field.value = value; field.dispatchEvent(new Event('input', { bubbles: true }))
  }
  host.querySelector<HTMLButtonElement>('[data-settings-target="models"]')!.click(); await flush()
  expect(host.querySelector('[name="api_key"]')).toBe(draft)
  expect(draft.value).toBe('fixture-unsaved')
  host.querySelector<HTMLButtonElement>('[data-settings-target="connections"]')!.click(); await flush(); await flush()
  expect(campusUrl.value).toBe('https://draft.example.test/grades')
  expect(webKey.value).toBe('fixture-search-key')
  expect(campusCalls).toBe(1)
  expect(webCalls).toBe(1)
  host.querySelector<HTMLButtonElement>('[data-settings-target="usage"]')!.click()
  for (let index = 0; index < 12; index++) await flush()
  expect(usageCalls).toBe(1)
  expect(host.querySelector('.usage-settings')).not.toBeNull()
})

it('lets an initial campus-source load retry without restarting or refreshing other connection drafts', async () => {
  setLocale('en'); localStorage.setItem('mens-onboarding-done', '1')
  let campusCalls = 0
  vi.stubGlobal('fetch', async (value: string) => {
    const url = String(value)
    if (url.endsWith('/health')) return Response.json({ status: 'ok', models: {} })
    if (url.endsWith('/models/config')) return Response.json({ providers: {}, ollama: { model: '' } })
    if (url.endsWith('/models/local')) return Response.json({ running: false, installed: [], catalog: [], sources: [] })
    if (url.endsWith('/web/status')) return Response.json({ enabled: false, available: false, provider: 'bing', max_results: 5, fetch_pages: 2, providers: [] })
    if (url.endsWith('/campus-sources')) {
      campusCalls++
      return campusCalls === 1 ? Response.json({ detail: 'Temporary campus failure' }, { status: 503 }) : Response.json([{ kind: 'grades', label: 'Grades', url: 'https://school.example.test/grades', result_path: 'data', configured: true, has_token: false }])
    }
    return Response.json([])
  })
  const host = document.createElement('div'); document.body.append(host)
  const pinia = createPinia(); const app = createApp(App).use(pinia).use(campusUi)
  app.mount(host); dispose = () => { app.unmount(); host.remove() }
  for (let index = 0; index < 4; index++) await flush()
  const store = useWorkspaceStore(pinia)
  store.view = 'settings'; await flush()
  host.querySelector<HTMLButtonElement>('[data-settings-target="connections"]')!.click(); await flush(); await flush()
  const retry = host.querySelector<HTMLButtonElement>('[data-campus-retry]')
  expect(retry?.textContent).toBe('Retry loading campus interfaces')
  const webKey = host.querySelector<HTMLInputElement>('.web-form input[type="password"]')!
  webKey.value = 'keep-web-draft'; webKey.dispatchEvent(new Event('input', { bubbles: true }))
  retry!.click(); await flush(); await flush()
  expect(campusCalls).toBe(2)
  expect(host.querySelector('[data-campus-retry]')).toBeNull()
  expect(host.querySelector<HTMLInputElement>('#campus-source-settings input[placeholder="https://school.edu/api/grades"]')?.value).toBe('https://school.example.test/grades')
  expect(webKey.value).toBe('keep-web-draft')
})
