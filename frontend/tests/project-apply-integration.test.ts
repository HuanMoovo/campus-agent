import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, reactive } from 'vue'
import ElementPlus from 'element-plus'
import ProjectFiles from '../src/components/ProjectFiles.vue'
import { setLocale } from '../src/i18n'

const bridge = vi.hoisted(() => ({ desktop: { isDesktop: true, pickProject: vi.fn(), projectChanges: vi.fn(), changeProjectFile: vi.fn(), projectChangeStatus: vi.fn(), projectRecoveryOriginal: vi.fn() } }))
vi.mock('../src/desktop', () => bridge)
let dispose = () => {}
const before = 'value = 1\n'; const after = 'value = 2000\n'
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
beforeEach(() => { vi.resetAllMocks(); setLocale('zh') })
afterEach(() => { dispose(); vi.unstubAllGlobals(); document.querySelectorAll('.el-overlay, .el-popper-container').forEach(node => node.remove()) })

async function setup(cancel = false) {
  let content = before
  let records: Record<string, unknown>[] = []
  const requests: Record<string, unknown>[] = []
  bridge.desktop.projectChanges.mockImplementation(async () => ({ available: true, records }))
  bridge.desktop.changeProjectFile.mockImplementation(async (projectId, subjectId, action) => {
    const receipt = { project_id: projectId, subject_id: subjectId, proposal_id: 'draft', operation_id: `op-${action}`, recovery_id: 'recovery', action, path: 'main.py', summary: 'fixture', created_at: '2026-10-31T00:00:00Z', state: cancel ? 'cancelled' : action === 'apply' ? 'applied' : 'reverted', can_revert: !cancel && action === 'apply' }
    if (!cancel) { content = action === 'apply' ? after : before; records = [receipt] }
    return receipt
  })
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (url.endsWith('/projects')) return Response.json({ available: true, changes_available: true, project: { id: 'root', name: 'fixture' }, limits: { max_files: 4, max_context_chars: 16000 } })
    if (url.includes('/files?')) return Response.json({ project: { id: 'root', name: 'fixture' }, path: '', entries: [{ name: 'main.py', path: 'main.py', kind: 'file', readable: true, size_bytes: before.length }], truncated: false })
    if (url.endsWith('/read')) return Response.json({ path: 'main.py', text: content, start_line: 1, end_line: 1, size_bytes: content.length, truncated: false, excerpt_sha256: content === before ? 'a'.repeat(64) : 'b'.repeat(64) })
    if (url.endsWith('/proposals')) {
      requests.push(JSON.parse(String(init?.body)))
      return Response.json({ id: 'draft', project_id: 'root', path: 'main.py', state: 'ready', summary: 'fixture', before_text: before, after_text: after, diff: '', diff_lines: [{ kind: 'remove', text: 'value = 1', old_line: 1, new_line: null }, { kind: 'add', text: 'value = 2000', old_line: null, new_line: 1 }], added_lines: 1, removed_lines: 1, base_sha256: 'a'.repeat(64), proposed_sha256: 'b'.repeat(64), model: 'openai_responses', model_name: 'fixture-model', bom: false, newline: 'lf', created_at: '2026-10-31T00:00:00Z' })
    }
    return Response.json([])
  })
  const host = document.createElement('div'); document.body.append(host)
  const state = reactive({ modelValue: null, connected: true, model: 'openai_responses', reasoning: 'high' })
  const app = createApp({ render: () => h(ProjectFiles, state as never) }).use(ElementPlus)
  app.mount(host); dispose = () => { app.unmount(); host.remove() }
  for (let i = 0; i < 4; i++) await flush()
  host.querySelector<HTMLElement>('.project-preview-file')!.click(); await flush(); await flush()
  host.querySelector<HTMLButtonElement>('.project-propose')!.click(); await flush()
  const input = document.querySelector<HTMLTextAreaElement>('.proposal-instruction')!
  input.value = 'update value'; input.dispatchEvent(new Event('input', { bubbles: true })); await nextTick()
  document.querySelector<HTMLButtonElement>('.proposal-generate')!.click(); await flush(); await flush()
  return { host, requests }
}

it('applies and undoes through native IDs, restores the recovery entry, and refreshes the file preview', async () => {
  const { host, requests } = await setup()
  expect(requests[0]).toMatchObject({ model: 'openai_responses', reasoning: 'high', path: 'main.py' })
  document.querySelector<HTMLButtonElement>('.project-proposal-dialog [data-change-action="apply"]')!.click()
  for (let i = 0; i < 4; i++) await flush()
  expect(bridge.desktop.changeProjectFile).toHaveBeenLastCalledWith('root', 'draft', 'apply')
  expect(document.querySelector('.project-proposal-dialog')!.textContent).toContain('已应用')
  document.querySelector<HTMLButtonElement>('.proposal-close')!.click()
  for (let i = 0; i < 5; i++) await flush()
  expect(host.querySelector('.project-preview pre')?.textContent).toBe(after)
  expect(host.querySelector('.project-entries small')?.textContent).toBe(`${after.length} B`)
  expect(host.querySelector('.project-recoveries')?.textContent).toContain('main.py')
  host.querySelector<HTMLDetailsElement>('.project-recoveries')!.open = true
  host.querySelector<HTMLButtonElement>('.project-recoveries [data-change-action="revert"]')!.click()
  for (let i = 0; i < 5; i++) await flush()
  expect(bridge.desktop.changeProjectFile).toHaveBeenLastCalledWith('root', 'recovery', 'revert')
  expect(host.querySelector('.project-preview pre')?.textContent).toBe(before)
  expect(host.querySelector('.project-entries small')?.textContent).toBe(`${before.length} B`)
  expect(requests).toHaveLength(1)
})

it('leaves the preview and recovery list unchanged when native confirmation is cancelled', async () => {
  const { host } = await setup(true)
  document.querySelector<HTMLButtonElement>('.project-proposal-dialog [data-change-action="apply"]')!.click(); await flush(); await flush()
  expect(document.querySelector('.project-proposal-dialog')!.textContent).toContain('已取消')
  document.querySelector<HTMLButtonElement>('.proposal-close')!.click(); await flush(); await flush()
  expect(host.querySelector('.project-preview pre')?.textContent).toBe(before)
  expect(host.querySelector('.project-recoveries')?.textContent).toContain('暂无修改记录')
})
