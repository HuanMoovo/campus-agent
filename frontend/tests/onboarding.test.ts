import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { campusUi } from '../src/ui'
import App from '../src/App.vue'
import { useWorkspaceStore } from '../src/store'
import { setLocale } from '../src/i18n'

const bridge = vi.hoisted(() => ({ desktop: undefined as any }))
vi.mock('../src/desktop', () => bridge)
let dispose = () => {}
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
beforeEach(() => {
  localStorage.clear(); setLocale('zh'); bridge.desktop = undefined
  vi.stubGlobal('fetch', async (url: string) => {
    if (url.endsWith('/health')) return Response.json({ status: 'ok', models: {} })
    if (url.endsWith('/models/config')) return Response.json({ providers: {}, ollama: { model: '' } })
    if (url.endsWith('/models/local')) return Response.json({ running: false, installed: [], catalog: [], sources: [] })
    if (url.endsWith('/web/status')) return Response.json({ enabled: false, available: false, providers: [] })
    return Response.json([])
  })
})
afterEach(() => {
  dispose(); vi.unstubAllGlobals(); localStorage.clear()
  document.querySelectorAll('.el-popper-container, .el-message').forEach(node => node.remove())
})
async function mount() {
  const host = document.createElement('div'); document.body.append(host)
  const pinia = createPinia(); const app = createApp(App).use(pinia).use(campusUi)
  app.mount(host)
  dispose = () => { app.unmount(); host.remove() }
  for (let i = 0; i < 5; i++) await flush()
  return { host, store: useWorkspaceStore(pinia) }
}
function desktopDisk(onboardingDone?: unknown) {
  const disk: any = { model: 'auto', conversationId: '', clientId: 'fixture-client', localModel: '',
    appearance: 'system', accentColor: '#147b75', webSearch: false, reasoning: 'auto', projectPermission: 'confirm',
    ...(onboardingDone !== undefined ? { onboardingDone } : {}) }
  bridge.desktop = {
    isDesktop: true,
    loadWorkspace: vi.fn(async () => ({ ...disk })),
    saveWorkspace: vi.fn(async (value: any) => { Object.assign(disk, value) }),
    getInfo: vi.fn(async () => ({ version: 'test', dataPath: '' })),
  }
  return disk
}

it('keeps desktop onboarding completed when a new launch has empty origin storage', async () => {
  const disk = desktopDisk()
  const first = await mount()
  expect(first.host.querySelector('.onboarding')).not.toBeNull()
  first.host.querySelector<HTMLButtonElement>('.onboarding button')!.click()
  await flush(); await first.store.flushWorkspace()
  expect(first.host.querySelector('.onboarding')).toBeNull()
  dispose()
  // A different random backend port starts with a separate, empty localStorage origin.
  localStorage.clear()
  const restarted = await mount()
  expect(restarted.host.querySelector('.onboarding')).toBeNull()
  expect(disk.onboardingDone).toBe(true)
})

it('uses the desktop completion flag even when localStorage is empty', async () => {
  desktopDisk(true)
  const { host } = await mount()
  expect(host.querySelector('.onboarding')).toBeNull()
  expect(localStorage.getItem('mens-onboarding-done')).toBeNull()
})

it.each([undefined, false, 'true', 1])('treats desktop legacy or non-boolean completion %s as incomplete', async saved => {
  desktopDisk(saved)
  localStorage.setItem('mens-onboarding-done', '1')
  const { host } = await mount()
  expect(host.querySelector('.onboarding')).not.toBeNull()
})

it('retains a desktop persistence error when completion cannot be written', async () => {
  desktopDisk(false)
  const { host, store } = await mount()
  bridge.desktop.saveWorkspace.mockRejectedValue(new Error('fixture disk unavailable'))
  host.querySelector<HTMLButtonElement>('.onboarding button')!.click()
  await flush()
  expect(await store.flushWorkspace()).toBe(false)
  expect(store.persistenceError).toContain('fixture disk unavailable')
})

it('does not offer first-run completion before a failed desktop workspace read recovers', async () => {
  const disk = desktopDisk(true)
  bridge.desktop.loadWorkspace.mockRejectedValue(new Error('fixture read unavailable'))
  const { host, store } = await mount()
  expect(store.ready).toBe(false)
  expect(host.querySelector('.onboarding')).toBeNull()
  expect(bridge.desktop.saveWorkspace).not.toHaveBeenCalled()
  expect(disk.onboardingDone).toBe(true)
})

it('can close a manually reopened tour while workspace recovery is unavailable without writing', async () => {
  desktopDisk(true)
  bridge.desktop.loadWorkspace.mockRejectedValue(new Error('fixture read unavailable'))
  const { host, store } = await mount()
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }))
  await flush()
  const command = [...host.querySelectorAll<HTMLButtonElement>('.palette-item')]
    .find(button => button.textContent?.includes('查看使用引导'))!
  expect(command).toBeDefined()
  command.click(); await flush()
  expect(host.querySelector('.onboarding')).not.toBeNull()
  host.querySelector<HTMLButtonElement>('.onboarding button')!.click()
  await flush()
  expect(host.querySelector('.onboarding')).toBeNull()
  expect(store.ready).toBe(false)
  expect(bridge.desktop.saveWorkspace).not.toHaveBeenCalled()
})

it('preserves web onboarding completion in the existing localStorage key', async () => {
  const first = await mount()
  expect(first.host.querySelector('.onboarding')).not.toBeNull()
  first.host.querySelector<HTMLButtonElement>('.onboarding button')!.click()
  await flush()
  expect(localStorage.getItem('mens-onboarding-done')).toBe('1')
  dispose()
  const next = await mount()
  expect(next.host.querySelector('.onboarding')).toBeNull()
})

it('preserves the web behavior for an existing nonempty legacy completion key', async () => {
  localStorage.setItem('mens-onboarding-done', 'legacy-done')
  const { host } = await mount()
  expect(host.querySelector('.onboarding')).toBeNull()
})

it('preserves the web behavior when localStorage reads are unavailable', async () => {
  const read = vi.spyOn(localStorage, 'getItem').mockImplementation(() => { throw new Error('storage blocked') })
  try {
    const { host } = await mount()
    expect(host.querySelector('.onboarding')).toBeNull()
  } finally { read.mockRestore() }
})
