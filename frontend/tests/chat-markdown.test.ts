// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, reactive } from 'vue'
import ChatMarkdown from '../src/components/ChatMarkdown.vue'
import { createChatMarkdown } from '../src/chat-markdown'
import * as markdown from '../src/markdown'

const cleanup: (() => void)[] = []
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(0) })
afterEach(() => { cleanup.splice(0).forEach(dispose => dispose()); vi.restoreAllMocks(); vi.useRealTimers() })

it('bounds parse cadence, uses latest text, and flushes terminal text synchronously', () => {
  const parse = vi.spyOn(markdown, 'renderMarkdown')
  let html = ''
  const renderer = createChatMarkdown(value => { html = value })
  const id = {}
  renderer.update('', true, id)
  expect(parse).not.toHaveBeenCalled()
  renderer.update('first', true, id)
  expect(html).toBe('<p>first</p>\n')
  for (let i = 1; i <= 7; i++) {
    vi.advanceTimersByTime(10)
    renderer.update(`latest ${i}`, true, id)
  }
  expect(parse).toHaveBeenCalledTimes(1)
  vi.advanceTimersByTime(10)
  expect(html).toBe('<p>latest 7</p>\n')
  expect(parse).toHaveBeenCalledTimes(2)
  renderer.update('last pending', true, id)
  renderer.update('exact **final**', false, id)
  expect(html).toBe('<p>exact <strong>final</strong></p>\n')
  expect(vi.getTimerCount()).toBe(0)
  renderer.update('exact **final**', false, id)
  expect(parse).toHaveBeenCalledTimes(3)
})

it('cancels pending content when the same row is reused for another message', () => {
  let html = ''
  const renderer = createChatMarkdown(value => { html = value })
  const old = {}
  renderer.update('old', true, old)
  renderer.update('stale pending', true, old)
  renderer.update('', true, {})
  expect(html).toBe('')
  expect(vi.getTimerCount()).toBe(0)
  vi.advanceTimersByTime(100)
  expect(html).toBe('')
  renderer.update('new message', true, {})
  expect(html).toBe('<p>new message</p>\n')
})

it('sanitizes immediate, delayed and final HTML using the existing Markdown rules', () => {
  let html = ''
  const renderer = createChatMarkdown(value => { html = value })
  const id = {}
  const unsafe = '<img src=x onerror="alert(1)"><script>alert(1)</script>\n\n[unsafe](javascript:alert(1))'
  for (const [index, streaming] of [true, true, false].entries()) {
    renderer.update(`${unsafe}\n\nversion ${index}`, streaming, id)
    vi.advanceTimersByTime(80)
    expect(html).toContain(`version ${index}`)
    expect(html).not.toMatch(/<img|<script|onerror|javascript:/)
  }
})

it('isolates unchanged history from parent updates and cancels rendering on unmount', async () => {
  const parse = vi.spyOn(markdown, 'renderMarkdown')
  const props = reactive({ text: 'history **answer**', streaming: false, messageKey: {} })
  const parent = reactive({ counter: 0 })
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp({ render: () => h('div', [h('span', parent.counter), h(ChatMarkdown, props)]) })
  app.mount(host)
  const unmount = () => { app.unmount(); host.remove() }
  cleanup.push(unmount)
  for (let i = 0; i < 20; i++) { parent.counter++; await nextTick() }
  expect(parse).toHaveBeenCalledTimes(1)
  expect(host.querySelector('strong')?.textContent).toBe('answer')
  props.streaming = true; props.text = 'pending'; await nextTick()
  expect(vi.getTimerCount()).toBe(1)
  cleanup.pop()!()
  expect(vi.getTimerCount()).toBe(0)
  vi.advanceTimersByTime(100)
  expect(parse).toHaveBeenCalledTimes(1)
})
