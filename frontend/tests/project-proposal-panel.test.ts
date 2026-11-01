import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, reactive } from 'vue'
import ElementPlus from 'element-plus'
import ProjectFiles from '../src/components/ProjectFiles.vue'
import ProjectProposalPanel from '../src/components/ProjectProposalPanel.vue'
import { setLocale } from '../src/i18n'
import type { ProjectSelection } from '../src/project-files'

const bridge = vi.hoisted(() => ({ pick: vi.fn() }))
vi.mock('../src/desktop', () => ({ desktop: { isDesktop: true, pickProject: bridge.pick } }))
const disposals: Array<() => void> = []
const before = '<img src=x onerror="attack()">\nconst old = 1;\n'
const after = '<script>alert(1)</script>\nconst next = 2;\n'
const draft = (extra = {}) => ({
  id: 'draft-1', project_id: 'root-1', path: 'main.ts', state: 'ready', summary: '<b>Replace fixture</b>',
  before_text: before, after_text: after, diff: 'fixture unified diff', added_lines: 2, removed_lines: 2,
  base_sha256: 'base', proposed_sha256: 'after', created_at: '', model: 'qwen', model_name: 'fixture-model', bom: false, newline: 'lf',
  diff_lines: [
    { kind: 'header', text: '--- a/main.ts', old_line: null, new_line: null },
    { kind: 'header', text: '+++ b/main.ts', old_line: null, new_line: null },
    { kind: 'hunk', text: '@@ -1,2 +1,2 @@', old_line: null, new_line: null },
    { kind: 'remove', text: '<img src=x onerror="attack()">', old_line: 1, new_line: null },
    { kind: 'remove', text: 'const old = 1;', old_line: 2, new_line: null },
    { kind: 'add', text: '<script>alert(1)</script>', old_line: null, new_line: 1 },
    { kind: 'add', text: 'const next = 2;', old_line: null, new_line: 2 },
  ], ...extra,
})
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
function button(selector: string) { const node = document.querySelector<HTMLButtonElement>(selector); expect(node).not.toBeNull(); return node! }
function serve(custom?: (url: string, init?: RequestInit) => Promise<Response> | Response | undefined) {
  const calls: Array<[string, RequestInit | undefined]> = []
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    calls.push([url, init])
    const response = custom?.(url, init)
    if (response) return response
    if (url.endsWith('/proposals')) return Response.json(draft())
    if (url.includes('/proposals/')) return Response.json(draft())
    if (url.endsWith('/read')) return Response.json({ path: 'main.ts', text: before, start_line: 1, end_line: 2, size_bytes: before.length, truncated: false, excerpt_sha256: 'base' })
    if (url.endsWith('/projects')) return Response.json({ available: true, project: { id: 'root-1', name: 'fixture' }, limits: { max_files: 4, max_context_chars: 16000 } })
    return Response.json({ project: { id: 'root-1', name: 'fixture' }, path: '', entries: [{ name: 'main.ts', path: 'main.ts', kind: 'file', readable: true }], truncated: false })
  })
  return calls
}
async function mount() {
  const state = reactive({ modelValue: null as ProjectSelection | null, model: 'qwen3', localModel: '', reasoning: 'high' as const, connected: true })
  const busy: boolean[] = []
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp({ render: () => h(ProjectFiles, { ...state, 'onUpdate:modelValue': (value: ProjectSelection | null) => { state.modelValue = value }, onBusy: (value: boolean) => busy.push(value) }) }).use(ElementPlus)
  app.mount(host)
  disposals.push(() => { app.unmount(); host.remove() })
  await flush(); await flush()
  button('.project-preview-file').click(); await flush()
  button('.project-propose').click(); await flush()
  return { state, busy, host }
}
async function generate() {
  const input = document.querySelector<HTMLTextAreaElement>('.proposal-instruction')!
  expect(input).not.toBeNull()
  input.value = 'Replace the fixture'; input.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
  button('.proposal-generate').click(); await flush(); await flush()
}
async function mountPanel() {
  const state = reactive({ modelValue: true, projectId: 'root-1', path: 'main.ts', connected: true })
  const busy: boolean[] = []
  const host = document.createElement('div'); document.body.append(host)
  const app = createApp({ render: () => h(ProjectProposalPanel, { ...state, 'onUpdate:modelValue': (value: boolean) => { state.modelValue = value }, onBusy: (value: boolean) => busy.push(value) }) }).use(ElementPlus)
  app.mount(host); disposals.push(() => { app.unmount(); host.remove() }); await flush()
  return { state, busy }
}
let clipboardDescriptor: PropertyDescriptor | undefined
let copied: string[]
beforeEach(() => {
  setLocale('zh'); copied = []; localStorage.clear()
  clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text: string) => { copied.push(text) } } })
})
afterEach(() => {
  disposals.splice(0).forEach(dispose => dispose()); vi.unstubAllGlobals()
  if (clipboardDescriptor) Object.defineProperty(navigator, 'clipboard', clipboardDescriptor)
  else Reflect.deleteProperty(navigator, 'clipboard')
  document.querySelectorAll('.el-overlay').forEach(node => node.remove())
})

describe('explicit read-only project proposals', () => {
  it('opens without a request, generates explicitly, and safely renders full diff and file views', async () => {
    const calls = serve()
    await mount()
    expect(calls.some(([url]) => url.includes('/proposals'))).toBe(false)
    await generate()
    const created = calls.filter(([url]) => url.endsWith('/proposals'))
    expect(created).toHaveLength(1)
    expect(JSON.parse(String(created[0]![1]?.body))).toEqual({ path: 'main.ts', instruction: 'Replace the fixture', model: 'qwen', reasoning: 'high' })
    const diff = document.querySelector('.proposal-diff')!
    expect(diff.textContent).toContain('@@ -1,2 +1,2 @@')
    expect(diff.textContent).toContain('<script>alert(1)</script>')
    expect(diff.querySelector('script, img')).toBeNull()
    expect(document.querySelector('.proposal-summary')!.textContent).toContain('<b>Replace fixture</b>')
    expect(document.querySelector('.proposal-summary b')).toBeNull()
    expect(document.querySelector('.proposal-model')!.textContent).toContain('fixture-model')
    expect(document.querySelectorAll('.diff-add')).toHaveLength(2)
    expect(document.querySelectorAll('.diff-remove')).toHaveLength(2)
    expect([...document.querySelectorAll('.diff-add .diff-new-line')].map(node => node.textContent)).toEqual(['1', '2'])
    button('.proposal-view-before').click(); await nextTick()
    expect(document.querySelector('.proposal-file-text')!.textContent).toBe(before)
    button('.proposal-view-after').click(); await nextTick()
    expect(document.querySelector('.proposal-file-text')!.textContent).toBe(after)
    expect(document.querySelector('.proposal-apply')).toBeNull()
    expect(localStorage.length).toBe(0)
  })

  it('rechecks the original file before copying and blocks copying a conflicting proposal', async () => {
    const calls = serve(url => url.includes('/proposals/') ? Response.json(draft({ state: 'conflict' })) : undefined)
    await mount(); await generate()
    button('.proposal-copy').click(); await flush(); await flush()
    expect(copied).toEqual([])
    expect(document.querySelector('.proposal-conflict')).not.toBeNull()
    expect(button('.proposal-copy').disabled).toBe(true)
    expect(calls.filter(([url]) => url.endsWith('/proposals'))).toHaveLength(1)
    expect(calls.filter(([url]) => url.includes('/proposals/'))).toHaveLength(1)
  })

  it('checks with GET before copying only the validated modified file', async () => {
    const calls = serve()
    await mount(); await generate()
    button('.proposal-check').click(); await flush(); await flush()
    button('.proposal-copy').click(); await flush(); await flush()
    expect(copied).toEqual([after])
    expect(calls.filter(([url]) => url.endsWith('/proposals'))).toHaveLength(1)
    expect(calls.filter(([url]) => url.includes('/proposals/')).map(([, init]) => init?.method || 'GET')).toEqual(['GET', 'GET'])
  })

  it('discards generation results after disconnect and releases the parent busy state', async () => {
    const pending = deferred<Response>()
    serve(url => url.endsWith('/proposals') ? pending.promise : undefined)
    const { state, busy } = await mount(); await generate()
    expect(button('.project-pick').disabled).toBe(true)
    expect(busy.at(-1)).toBe(true)
    state.connected = false; await flush()
    pending.resolve(Response.json(draft({ summary: 'stale result must disappear' }))); await flush(); await flush()
    expect(document.body.textContent).not.toContain('stale result must disappear')
    expect(busy.at(-1)).toBe(false)
  })

  it('keeps generation busy when the dialog is merely hidden', async () => {
    const pending = deferred<Response>()
    serve(url => url.endsWith('/proposals') ? pending.promise : undefined)
    const { busy } = await mount(); await generate()
    button('.proposal-close').click(); await nextTick()
    expect(busy.at(-1)).toBe(true)
    expect(button('.project-close').disabled).toBe(true)
    pending.resolve(Response.json(draft())); await flush(); await flush()
    expect(busy.at(-1)).toBe(false)
  })

  it('makes byte-format-only changes visible even with no added or removed lines', async () => {
    serve(url => url.endsWith('/proposals') ? Response.json(draft({ bom: true, newline: 'lf', after_newline: 'crlf', added_lines: 0, removed_lines: 0 })) : undefined)
    await mount(); await generate()
    expect(document.querySelector('.proposal-format')?.textContent).toContain('UTF-8')
    expect(document.querySelector('.proposal-format')?.textContent).toContain('BOM')
    expect(document.querySelector('.proposal-format')?.textContent).toContain('LF → CRLF')
  })

  it.each(['path', 'projectId'] as const)('discards an older generation after %s changes while a newer one is pending', async key => {
    const older = deferred<Response>(); const newer = deferred<Response>()
    let count = 0
    serve(url => url.endsWith('/proposals') ? ++count === 1 ? older.promise : newer.promise : undefined)
    const { state, busy } = await mountPanel(); await generate()
    state[key] = key === 'path' ? 'other.ts' : 'root-2'; await nextTick()
    state.modelValue = true; await flush(); await generate()
    older.resolve(Response.json(draft({ summary: 'old late proposal' }))); await flush(); await flush()
    expect(document.body.textContent).not.toContain('old late proposal')
    expect(busy.at(-1)).toBe(true)
    newer.resolve(Response.json(draft({ id: 'draft-2', project_id: state.projectId, path: state.path, summary: 'current proposal' }))); await flush(); await flush()
    expect(document.querySelector('.proposal-summary')!.textContent).toContain('current proposal')
    expect(busy.at(-1)).toBe(false)
  })

  it('does not copy a late validation response after the preview target changes', async () => {
    const checked = deferred<Response>()
    serve(url => url.includes('/proposals/') ? checked.promise : undefined)
    const { state } = await mountPanel(); await generate()
    button('.proposal-copy').click(); await nextTick()
    state.path = 'other.ts'; await nextTick()
    checked.resolve(Response.json(draft())); await flush(); await flush()
    expect(copied).toEqual([])
  })
})
