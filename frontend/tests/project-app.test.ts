import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { campusUi } from '../src/ui'
import App from '../src/App.vue'
import { useWorkspaceStore } from '../src/store'
import { setLocale } from '../src/i18n'

const bridge = vi.hoisted(() => ({
  desktop: {
    isDesktop: true,
    loadWorkspace: vi.fn(async () => ({ model: 'auto', conversationId: '', clientId: 'fixture-client', localModel: '', appearance: 'light', accentColor: '#000000', webSearch: false, reasoning: 'fast' })),
    saveWorkspace: vi.fn(async () => {}), getInfo: vi.fn(async () => ({ version: 'test', dataPath: '' })),
    setProjectPermission: vi.fn(async (projectPermission: 'confirm' | 'read_only') => ({ projectPermission, persisted: true })),
    pickProject: vi.fn(async () => ({ picked: true, project: { id: 'other', name: 'other' } })),
    saveBackup: vi.fn(async () => ({ saved: true, path: 'synthetic-backup.zip' })),
  },
}))
vi.mock('../src/desktop', () => bridge)
let dispose = () => {}
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
beforeEach(() => { localStorage.clear(); localStorage.setItem('mens-onboarding-done', '1'); setLocale('zh'); bridge.desktop.saveWorkspace.mockClear(); bridge.desktop.loadWorkspace.mockImplementation(async () => ({ model: 'auto', conversationId: '', clientId: 'fixture-client', localModel: '', appearance: 'light', accentColor: '#000000', webSearch: false, reasoning: 'fast' })) })
afterEach(() => { dispose(); vi.unstubAllGlobals(); document.querySelectorAll('.el-popper-container, .el-message').forEach(node => node.remove()) })
async function setup(history?: unknown[]) {
  if (history) bridge.desktop.loadWorkspace.mockResolvedValue({ model: 'auto', conversationId: 'history', clientId: 'fixture-client', localModel: '', appearance: 'light', accentColor: '#000000', webSearch: false, reasoning: 'fast' })
  const requests: any[] = []
  const proposalRequests: any[] = []
  const backupRequests: string[] = []
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (url.includes('/backup/export')) { backupRequests.push(url); return new Response('synthetic-zip') }
    if (url.endsWith('/chat/stream')) {
      requests.push(JSON.parse(String(init?.body)))
      return new Response(`event: done\ndata: ${JSON.stringify({ conversation_id: 'chat', answer: 'fixture answer', sources: [{ title: 'main.ts', kind: 'project', path: 'main.ts', start_line: 1, end_line: 3, truncated: true, excerpt_sha256: 'fixture' }] })}\n\n`)
    }
    if (url.endsWith('/health')) return Response.json({ status: 'ok', models: {} })
    if (url.endsWith('/models/config')) return Response.json({ providers: { qwen: { configured: true, model: 'fixture-qwen', base_url: '', reasoning: { mode: 'effort', levels: ['low', 'high'] } } }, ollama: { model: '' } })
    if (url.endsWith('/models/local')) return Response.json({ running: false, installed: [], catalog: [], sources: [] })
    if (url.endsWith('/web/status')) return Response.json({ enabled: false, available: false, providers: [] })
    if (url.endsWith('/projects')) return Response.json({ available: true, project: { id: 'fixture', name: 'fixture' }, limits: { max_files: 4, max_context_chars: 16000 } })
    if (url.includes('/files?')) return Response.json({ project: { id: 'fixture', name: 'fixture' }, path: '', entries: [{ name: 'main.ts', path: 'main.ts', kind: 'file', readable: true }], truncated: false })
    if (url.endsWith('/read')) return Response.json({ path: 'main.ts', text: 'old fixture\n', start_line: 1, end_line: 1, size_bytes: 12, truncated: false, excerpt_sha256: 'fixture' })
    if (url.endsWith('/proposals')) {
      const body = JSON.parse(String(init?.body)); proposalRequests.push(body)
      return Response.json({ id: 'draft', project_id: 'fixture', path: body.path, state: 'ready', summary: 'proposal-private-fixture', before_text: 'old fixture\n', after_text: 'new fixture\n', diff: '', diff_lines: [], added_lines: 1, removed_lines: 1, base_sha256: 'old', proposed_sha256: 'new', created_at: '', model: body.model, model_name: 'fixture-qwen', bom: false, newline: 'lf' })
    }
    if (url.includes('/conversations/history?')) return Response.json({ id: 'history', messages: history })
    return Response.json([])
  })
  const host = document.createElement('div'); document.body.append(host)
  const pinia = createPinia(); const app = createApp(App).use(pinia).use(campusUi)
  app.mount(host); dispose = () => { app.unmount(); host.remove() }
  for (let i = 0; i < 5; i++) await flush()
  return { host, requests, proposalRequests, backupRequests, store: useWorkspaceStore(pinia) }
}
async function ask(host: HTMLElement, question = 'review fixture') {
  const input = host.querySelector<HTMLTextAreaElement>('.composer textarea')!
  input.value = question; input.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
  host.querySelector<HTMLButtonElement>('.composer-send')!.click()
  for (let i = 0; i < 3; i++) await flush()
}

it('integrates project refs into questions and retries, keeps next-question refs visible and renders line citations', async () => {
  const { host, requests, store } = await setup()
  host.querySelector<HTMLInputElement>('.project-files input[type="checkbox"]')!.click(); await nextTick()
  await ask(host)
  expect(requests[0]).toMatchObject({ message: 'review fixture', project: { id: 'fixture', files: ['main.ts'] } })
  expect(requests[0].attachments).toBeUndefined()
  expect(host.querySelector('.message-row.user')!.textContent).toContain('[项目文件] main.ts')
  expect(host.querySelector('.source-item')!.textContent).toContain('main.ts:1–3')
  expect(host.querySelector('.source-item')!.textContent).toContain('截断')
  expect(host.querySelector('.project-selected')!.textContent).toContain('main.ts')
  const retry = [...host.querySelectorAll<HTMLButtonElement>('.message-action')].find(node => node.textContent === '重新生成')!
  retry.click(); await flush(); await flush()
  expect(requests[1]).toMatchObject({ regenerate: true, project: { id: 'fixture', files: ['main.ts'] } })
  store.view = 'settings'; await flush(); store.view = 'chat'; await flush(); await flush()
  expect(host.querySelector('.project-selected')!.textContent).toContain('main.ts')
  await store.flushWorkspace()
  expect(JSON.stringify(bridge.desktop.saveWorkspace.mock.calls)).not.toContain('main.ts')
})

it('blocks a retry after root reselection instead of using the newly selected project', async () => {
  const { host, requests } = await setup()
  host.querySelector<HTMLInputElement>('.project-files input[type="checkbox"]')!.click(); await nextTick()
  await ask(host)
  host.querySelector<HTMLButtonElement>('.project-pick')!.click(); await flush(); await flush()
  host.querySelector<HTMLInputElement>('.project-files input[type="checkbox"]')!.click(); await nextTick()
  ;[...host.querySelectorAll<HTMLButtonElement>('.message-action')].find(node => node.textContent === '重新生成')!.click()
  await flush()
  expect(requests).toHaveLength(1)
  expect(document.body.textContent).toContain('重新勾选相同文件')
})

it('blocks history retries even with matching names, and allows a new explicitly selected question', async () => {
  const { host, requests } = await setup([
    { role: 'user', content: 'review history\n\n[项目文件] main.ts', created_at: '' },
    { role: 'assistant', content: 'old answer', created_at: '', sources: [{ title: 'main.ts', kind: 'project', path: 'main.ts' }] },
  ])
  const retry = () => [...host.querySelectorAll<HTMLButtonElement>('.message-action')].find(node => node.textContent === '重新生成')!.click()
  retry(); await flush(); expect(requests).toHaveLength(0)
  host.querySelector<HTMLInputElement>('.project-files input[type="checkbox"]')!.click(); await nextTick()
  retry(); await flush(); await flush()
  expect(requests).toHaveLength(0)
  await ask(host, 'review the selected files again')
  expect(requests[0]).toMatchObject({ message: 'review the selected files again', project: { id: 'fixture', files: ['main.ts'] } })
  expect(requests[0].regenerate).toBeUndefined()
})

it('generates proposals with the currently selected model and effective reasoning without persisting file contents', async () => {
  const { host, proposalRequests, store } = await setup()
  store.setModel('qwen3'); store.setReasoning('high'); await nextTick()
  host.querySelector<HTMLButtonElement>('.project-preview-file')!.click(); await flush()
  host.querySelector<HTMLButtonElement>('.project-propose')!.click(); await flush()
  const input = document.querySelector<HTMLTextAreaElement>('.proposal-instruction')!
  input.value = 'Simplify the fixture'; input.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
  document.querySelector<HTMLButtonElement>('.proposal-generate')!.click(); await flush(); await flush()
  expect(proposalRequests).toEqual([{ path: 'main.ts', instruction: 'Simplify the fixture', model: 'qwen', reasoning: 'high' }])
  expect(document.querySelector('.proposal-model')!.textContent).toContain('fixture-qwen')
  await store.flushWorkspace()
  expect(JSON.stringify(bridge.desktop.saveWorkspace.mock.calls)).not.toContain('proposal-private-fixture')
  expect(JSON.stringify(bridge.desktop.saveWorkspace.mock.calls)).not.toContain('old fixture')
})

it('persists desktop permission selection while keeping file preview and proposals usable in read-only mode', async () => {
  const { host, store, proposalRequests } = await setup()
  expect(store.projectPermission).toBe('confirm')
  host.querySelector<HTMLElement>('.chat-permission-picker .el-select__wrapper')!.click(); await flush()
  const readOnly = [...document.querySelectorAll<HTMLElement>('.chat-permission-menu .el-select-dropdown__item')].find(node => node.textContent?.startsWith('只读'))!
  expect(readOnly).toBeTruthy(); readOnly.click(); await flush(); await store.flushWorkspace()
  expect(store.projectPermission).toBe('read_only')
  expect(bridge.desktop.setProjectPermission).toHaveBeenLastCalledWith('read_only')
  host.querySelector<HTMLButtonElement>('.project-preview-file')!.click(); await flush()
  expect(host.querySelector('.project-preview pre')?.textContent).toContain('old fixture')
  host.querySelector<HTMLButtonElement>('.project-propose')!.click(); await flush()
  const instruction = document.querySelector<HTMLTextAreaElement>('.proposal-instruction')!
  instruction.value = 'Read-only proposal'; instruction.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
  document.querySelector<HTMLButtonElement>('.proposal-generate')!.click(); await flush(); await flush()
  expect(proposalRequests).toHaveLength(1)
  expect(document.querySelector('.project-change-actions')?.textContent).toContain('项目只读')
  expect(document.querySelector<HTMLButtonElement>('.proposal-copy')?.disabled).toBe(false)
  expect(document.querySelector('[data-change-action="apply"]')).toBeNull()
})

it.each([['en', 'Project permission'], ['ja', 'プロジェクト権限']] as const)('localizes the project permission control in %s', async (locale, label) => {
  const { host } = await setup(); setLocale(locale); await nextTick()
  expect(host.querySelector('label[for="chat-permission-select"]')?.textContent).toBe(label)
})

it('keeps project originals out of a settings export until the user checks the include option', async () => {
  const { host, backupRequests, store } = await setup()
  store.view = 'settings'; await flush()
  const checkbox = host.querySelector<HTMLInputElement>('.backup-recovery-choice input')!
  expect(checkbox.checked).toBe(false)
  const exportButton = [...host.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.trim() === '导出备份')!
  exportButton.click(); await flush(); await flush()
  expect(backupRequests).toEqual(['/api/backup/export'])
  checkbox.click(); await nextTick()
  exportButton.click(); await flush(); await flush()
  expect(backupRequests[1]).toBe('/api/backup/export?include_project_recoveries=true')
})
