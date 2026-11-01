import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, reactive } from 'vue'
import ProjectFiles from '../src/components/ProjectFiles.vue'
import { setLocale } from '../src/i18n'
import type { ProjectListing, ProjectSelection } from '../src/project-files'

const bridge = vi.hoisted(() => ({ enabled: true, pick: vi.fn() }))
vi.mock('../src/desktop', () => ({ get desktop() { return bridge.enabled ? { isDesktop: true, pickProject: bridge.pick } : undefined } }))
const disposals: Array<() => void> = []
const project = { id: 'fixture-a', name: 'fixture' }
const entries = Array.from({ length: 5 }, (_, i) => ({ name: `file${i}.ts`, path: `file${i}.ts`, kind: 'file' as const, readable: true }))
const listing = (id = project.id, path = ''): ProjectListing => ({ project: { id, name: id }, path, entries, truncated: false })
const status = () => ({ available: true, project, limits: { max_files: 4, max_context_chars: 16000 } })
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
function mount(extra: Record<string, unknown> = {}) {
  const state = reactive({ modelValue: null as ProjectSelection | null, disabled: false, connected: true, ...extra })
  const host = document.createElement('div'); document.body.append(host)
  const changes: Array<ProjectSelection | null> = []
  const app = createApp({ render: () => h(ProjectFiles, { ...state, 'onUpdate:modelValue': (value: ProjectSelection | null) => { state.modelValue = value; changes.push(value) } }) })
  app.mount(host)
  let mounted = true
  const dispose = () => { if (mounted) { mounted = false; app.unmount(); host.remove() } }; disposals.push(dispose)
  return { host, state, changes, dispose }
}
function serve(custom?: (url: string, init?: RequestInit) => Promise<Response> | Response | undefined) {
  const calls: string[] = []
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    calls.push(url)
    const response = custom?.(url, init)
    if (response) return response
    return Response.json(url.endsWith('/projects') ? status() : listing())
  })
  return calls
}
beforeEach(() => { bridge.enabled = true; bridge.pick.mockReset(); setLocale('zh') })
afterEach(() => { disposals.splice(0).forEach(dispose => dispose()); vi.unstubAllGlobals() })

describe('read-only project browser', () => {
  it('keeps browser-only users outside project APIs and native directory picking', async () => {
    bridge.enabled = false
    const calls = serve()
    const { host } = mount()
    await flush()
    expect(host.textContent).toContain('桌面')
    expect(host.querySelector('.project-pick')).toBeNull()
    expect(calls).toEqual([])
    expect(bridge.pick).not.toHaveBeenCalled()
  })

  it('starts collapsed, caps explicit selection at four, and keeps selections visible when collapsed', async () => {
    serve()
    const { host, state } = mount()
    await flush(); await flush()
    expect(host.querySelector<HTMLDetailsElement>('details')!.open).toBe(false)
    const boxes = [...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')]
    for (const box of boxes.slice(0, 4)) { box.click(); await nextTick() }
    expect(state.modelValue).toEqual({ id: project.id, files: entries.slice(0, 4).map(row => row.path) })
    expect(boxes[4]!.disabled).toBe(true)
    expect(host.querySelector('summary')!.textContent).toContain('4')
    expect(host.querySelector('.project-selected')!.textContent).toContain('file3.ts')
    host.querySelector<HTMLButtonElement>('.project-clear')!.click(); await nextTick()
    expect(state.modelValue?.files).toEqual([])
  })

  it('previews plain text locally with line and truncation details without selecting the file', async () => {
    serve(url => url.endsWith('/read') ? Response.json({ path: 'file0.ts', text: '<script>fixture</script>', start_line: 1, end_line: 9, size_bytes: 300000, truncated: true, excerpt_sha256: 'fixturehash' }) : undefined)
    const { host, state } = mount()
    await flush(); await flush()
    host.querySelector<HTMLButtonElement>('.project-preview-file')!.click()
    await flush()
    expect(host.querySelector('pre')!.textContent).toBe('<script>fixture</script>')
    expect(host.querySelector('pre script')).toBeNull()
    expect(host.querySelector('.project-preview')!.textContent).toContain('1–9')
    expect(host.querySelector('.project-preview')!.textContent).toContain('截断')
    expect(state.modelValue?.files).toEqual([])
    expect(host.querySelector<HTMLButtonElement>('.project-propose')!.disabled).toBe(true)
  })

  it('offers explicit proposal generation only after reading a complete file', async () => {
    const calls = serve(url => url.endsWith('/read') ? Response.json({ path: 'file0.ts', text: 'const fixture = 1\n', start_line: 1, end_line: 1, size_bytes: 18, truncated: false, excerpt_sha256: 'fixturehash' }) : undefined)
    const { host } = mount()
    await flush(); await flush()
    expect(host.querySelector('.project-propose')).toBeNull()
    host.querySelector<HTMLButtonElement>('.project-preview-file')!.click(); await flush()
    expect(host.querySelector<HTMLButtonElement>('.project-propose')!.disabled).toBe(false)
    expect(calls.some(url => url.includes('/proposals'))).toBe(false)
  })

  it('keeps the current selection when the native chooser is cancelled', async () => {
    serve(); bridge.pick.mockResolvedValue({ picked: false })
    const { host, state } = mount()
    await flush(); await flush()
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(); await nextTick()
    host.querySelector<HTMLButtonElement>('.project-pick')!.click(); await flush()
    expect(bridge.pick).toHaveBeenCalledExactlyOnceWith()
    expect(state.modelValue?.files).toEqual(['file0.ts'])
  })

  it('discards an old preview when a new root is chosen', async () => {
    const preview = deferred<Response>()
    serve(url => url.endsWith('/read') ? preview.promise : undefined)
    bridge.pick.mockResolvedValue({ picked: true, available: true, project: { id: 'fixture-b', name: 'new-fixture' } })
    const { host, state } = mount()
    await flush(); await flush()
    host.querySelector<HTMLButtonElement>('.project-preview-file')!.click(); await nextTick()
    host.querySelector<HTMLButtonElement>('.project-pick')!.click(); await flush(); await flush()
    preview.resolve(Response.json({ path: 'file0.ts', text: 'stale preview', start_line: 1, end_line: 1, size_bytes: 10, truncated: false, excerpt_sha256: 'old' }))
    await flush()
    expect(state.modelValue).toEqual({ id: 'fixture-b', files: [] })
    expect(host.textContent).not.toContain('stale preview')
  })

  it('discards old directory listings and local previews on close or disconnect', async () => {
    const pending = deferred<Response>()
    serve(url => url.includes('path=src') ? pending.promise : url.includes('/files') ? Response.json({ ...listing(), entries: [{ name: 'src', path: 'src', kind: 'directory' }] }) : undefined)
    const { host, state } = mount()
    await flush(); await flush()
    host.querySelector<HTMLButtonElement>('.project-directory')!.click(); await nextTick()
    state.connected = false; await nextTick()
    pending.resolve(Response.json({ ...listing(project.id, 'src'), entries: [{ name: 'stale', path: 'src/stale', kind: 'file' }] }))
    await flush()
    expect(state.modelValue).toBeNull()
    expect(host.textContent).not.toContain('stale')
  })

  it('blocks selection and root changes during generation and hides raw filesystem failures', async () => {
    serve(url => url.endsWith('/read') ? Promise.reject(new Error('C:/secret-root/private.env')) : undefined)
    const { host, state } = mount()
    await flush(); await flush()
    host.querySelector<HTMLButtonElement>('.project-preview-file')!.click(); await flush()
    expect(host.textContent).not.toContain('secret-root')
    expect(host.querySelector('[role="alert"]')).not.toBeNull()
    state.disabled = true; await nextTick()
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.disabled).toBe(true)
    expect(host.querySelector<HTMLButtonElement>('.project-pick')!.disabled).toBe(true)
  })

  it('clears previously held refs when project status cannot be verified', async () => {
    serve(url => url.endsWith('/projects') ? Promise.reject(new Error('private path')) : undefined)
    const { host, state } = mount({ modelValue: { id: 'old', files: ['main.ts'] } })
    await flush()
    expect(state.modelValue).toBeNull()
    expect(host.textContent).not.toContain('private path')
  })

  it('drops pending status results after unmount', async () => {
    const pending = deferred<Response>()
    const calls = serve(url => url.endsWith('/projects') ? pending.promise : undefined)
    const { changes, dispose } = mount()
    dispose()
    pending.resolve(Response.json(status())); await flush()
    expect(changes).toEqual([])
    expect(calls).toEqual(['/api/projects'])
  })

  it('navigates one directory at a time and clears refs and preview before close finishes', async () => {
    const closed = deferred<Response>()
    const calls = serve((url, init) => init?.method === 'DELETE' ? closed.promise : url.includes('path=src') ? Response.json({ ...listing(project.id, 'src'), truncated: true }) : url.includes('/files') ? Response.json({ ...listing(), entries: [{ name: 'src', path: 'src', kind: 'directory' }] }) : undefined)
    const { host, state } = mount()
    await flush(); await flush()
    host.querySelector<HTMLButtonElement>('.project-directory')!.click(); await flush()
    expect(calls.filter(url => url.includes('/files'))).toEqual(['/api/projects/fixture-a/files?path=', '/api/projects/fixture-a/files?path=src'])
    expect(host.querySelector('.project-breadcrumbs')!.textContent).toContain('src')
    expect(host.textContent).toContain('300')
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(); await nextTick()
    host.querySelector<HTMLButtonElement>('.project-close')!.click(); await nextTick()
    expect(state.modelValue).toBeNull()
    expect(host.querySelector('.project-entries')).toBeNull()
    closed.resolve(Response.json({ ok: true })); await flush()
  })
})
