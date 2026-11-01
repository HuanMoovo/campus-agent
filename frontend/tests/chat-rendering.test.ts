import { afterEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { campusUi } from '../src/ui'
import App from '../src/App.vue'
import { setLocale } from '../src/i18n'

let dispose = () => {}
let stream: ReadableStreamDefaultController<Uint8Array> | undefined
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }

afterEach(async () => {
  try { stream?.close() } catch { /* a done event cancels the reader */ }
  stream = undefined
  vi.useRealTimers(); await flush(); await flush()
  dispose(); vi.unstubAllGlobals(); localStorage.clear()
  document.querySelectorAll('.el-popper-container, .el-message').forEach(node => node.remove())
})

async function setup(documents?: () => Promise<Response>) {
  localStorage.clear(); localStorage.setItem('mens-onboarding-done', '1'); setLocale('zh')
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (url.endsWith('/chat/stream')) return new Response(new ReadableStream({ start(controller) {
      stream = controller
      init?.signal?.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')), { once: true })
    } }))
    if (url.endsWith('/documents') && documents) return documents()
    if (url.endsWith('/health')) return Response.json({ status: 'ok', models: {} })
    if (url.endsWith('/models/config')) return Response.json({ providers: {}, ollama: { model: '' } })
    if (url.endsWith('/models/local')) return Response.json({ running: false, installed: [], catalog: [], sources: [] })
    if (url.endsWith('/web/status')) return Response.json({ enabled: false, available: false, providers: [] })
    return Response.json([])
  })
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp(App).use(createPinia()).use(campusUi)
  app.mount(host); dispose = () => { app.unmount(); host.remove() }
  for (let i = 0; i < 5; i++) await flush()
  const input = host.querySelector<HTMLTextAreaElement>('.composer textarea')!
  input.value = 'synthetic question'; input.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
  host.querySelector<HTMLButtonElement>('.composer-send')!.click(); await flush()
  return host
}

async function event(type: string, data: unknown) {
  stream!.enqueue(new TextEncoder().encode(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`))
  for (let i = 0; i < 10; i++) await Promise.resolve()
  await nextTick()
}

it('shows first content immediately, bounds burst updates and flushes the exact final answer', async () => {
  const host = await setup()
  vi.useFakeTimers()
  await event('delta', { text: 'first' })
  expect(host.querySelector('.markdown-body')?.textContent).toBe('first\n')
  await event('delta', { text: ' second' })
  expect(host.querySelector('.markdown-body')?.textContent).toBe('first\n')
  await vi.advanceTimersByTimeAsync(79)
  expect(host.querySelector('.markdown-body')?.textContent).toBe('first\n')
  await event('done', { conversation_id: 'synthetic', answer: 'exact **final**', sources: [] })
  stream = undefined
  for (let i = 0; i < 10; i++) await Promise.resolve()
  await nextTick()
  expect(host.querySelector('.markdown-body strong')?.textContent).toBe('final')
  expect(host.querySelector('.markdown-body')?.textContent).toBe('exact final\n')
  await vi.advanceTimersByTimeAsync(100)
  expect(host.querySelector('.markdown-body')?.textContent).toBe('exact final\n')
})

it.each(['error', 'stop'])('flushes pending content after %s and removes old render work', async terminal => {
  const host = await setup()
  vi.useFakeTimers()
  await event('delta', { text: 'first' })
  await event('delta', { text: ' pending **safe**' })
  expect(host.querySelector('.markdown-body')?.textContent).toBe('first\n')
  if (terminal === 'error') {
    await event('error', { message: 'synthetic failure' })
  } else {
    host.querySelector<HTMLButtonElement>('.composer-stop')!.click()
  }
  for (let i = 0; i < 20; i++) await Promise.resolve()
  await nextTick()
  expect(host.querySelector('.markdown-body strong')?.textContent).toBe('safe')
  expect(host.querySelector('.message-actions')).toBeTruthy()
  const html = host.querySelector('.markdown-body')!.innerHTML
  await vi.advanceTimersByTimeAsync(100)
  expect(host.querySelector('.markdown-body')!.innerHTML).toBe(html)
})

it('uses the production installer for loading feedback and the resulting document table', async () => {
  let resolveDocuments!: (response: Response) => void
  const pending = new Promise<Response>(resolve => { resolveDocuments = resolve })
  const host = await setup(() => pending)
  host.querySelectorAll<HTMLButtonElement>('.sidebar-nav > .nav-item')[2]!.click()
  await flush(); await flush()
  expect(host.querySelector('.data-panel .el-loading-mask')).toBeTruthy()
  resolveDocuments(Response.json([{ id: 'synthetic-doc', title: 'Synthetic document', content: 'fixture', updated_at: '2026-10-31' }]))
  await flush(); await flush()
  expect(host.querySelector('.data-panel .el-table')?.textContent).toContain('Synthetic document')
  await vi.waitFor(() => expect(host.querySelector('.data-panel .el-loading-mask')).toBeNull())
})

it('coalesces burst scroll requests into one frame and cancels the frame on unmount', async () => {
  const frames: FrameRequestCallback[] = []
  const request = vi.fn((callback: FrameRequestCallback) => { frames.push(callback); return frames.length })
  const cancel = vi.fn()
  vi.stubGlobal('requestAnimationFrame', request); vi.stubGlobal('cancelAnimationFrame', cancel)
  await setup()
  // The initial send scroll is still waiting for its frame.
  const initial = request.mock.calls.length
  await event('delta', { text: 'one' })
  await event('delta', { text: ' two' })
  await event('delta', { text: ' three' })
  expect(request).toHaveBeenCalledTimes(initial)
  frames.at(-1)!(0)
  await event('delta', { text: ' four' })
  expect(request).toHaveBeenCalledTimes(initial + 1)
  dispose(); dispose = () => {}
  expect(cancel).toHaveBeenCalledWith(frames.length)
})

it('schedules a scroll after a deferred Markdown update reaches the DOM', async () => {
  const frames: FrameRequestCallback[] = []
  const request = vi.fn((callback: FrameRequestCallback) => { frames.push(callback); return frames.length })
  vi.stubGlobal('requestAnimationFrame', request); vi.stubGlobal('cancelAnimationFrame', vi.fn())
  const host = await setup()
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
  frames.at(-1)!(0)
  await event('delta', { text: 'first' })
  frames.at(-1)!(0)
  await event('delta', { text: ' pending' })
  frames.at(-1)!(0)
  const before = request.mock.calls.length
  expect(host.querySelector('.markdown-body')?.textContent).toBe('first\n')
  await vi.advanceTimersByTimeAsync(80)
  await nextTick()
  expect(host.querySelector('.markdown-body')?.textContent).toBe('first pending\n')
  expect(request).toHaveBeenCalledTimes(before + 1)
})
