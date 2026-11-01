import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, reactive } from 'vue'
import ProjectChangeActions from '../src/components/ProjectChangeActions.vue'
import { setLocale } from '../src/i18n'

const bridge = vi.hoisted(() => ({ desktop: {
  isDesktop: true, changeProjectFile: vi.fn(), projectChangeStatus: vi.fn(), projectRecoveryOriginal: vi.fn(),
} }))
vi.mock('../src/desktop', () => bridge)
const disposals: Array<() => void> = []
const applied = { operation_id: 'operation-1', project_id: 'root', subject_id: 'draft', proposal_id: 'draft', recovery_id: 'recovery-1', action: 'apply', state: 'applied', path: 'main.py', summary: 'fixture', created_at: '2026-10-31T00:00:00Z', can_revert: true }
async function flush() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
function mount(extra: Record<string, unknown> = {}) {
  const state = reactive({ projectId: 'root', proposalId: 'draft', available: true, connected: true, disabled: false, ...extra })
  const changed = vi.fn(); const busy = vi.fn(); const host = document.createElement('div'); document.body.append(host)
  const app = createApp({ render: () => h(ProjectChangeActions, { ...state, onChanged: changed, onBusy: busy }) })
  app.mount(host); disposals.push(() => { app.unmount(); host.remove() })
  return { host, state, changed, busy }
}
async function click(host: HTMLElement, action: string) {
  const button = host.querySelector<HTMLButtonElement>(`[data-change-action="${action}"]`)!
  expect(button).toBeTruthy(); button.click(); await flush(); await flush()
}
beforeEach(() => { setLocale('zh'); vi.clearAllMocks() })
afterEach(() => disposals.splice(0).forEach(dispose => dispose()))

it('passes only opaque IDs through native confirmation and uses the recovery ID for undo', async () => {
  bridge.desktop.changeProjectFile.mockResolvedValueOnce(applied).mockResolvedValueOnce({ ...applied, operation_id: 'operation-2', subject_id: 'recovery-1', action: 'revert', state: 'reverted', can_revert: false })
  const { host } = mount()
  await click(host, 'apply')
  expect(bridge.desktop.changeProjectFile).toHaveBeenNthCalledWith(1, 'root', 'draft', 'apply')
  expect(host.textContent).toContain('已应用')
  await click(host, 'revert')
  expect(bridge.desktop.changeProjectFile).toHaveBeenNthCalledWith(2, 'root', 'recovery-1', 'revert')
  expect(host.textContent).toContain('已撤销')
  expect(host.querySelector('[data-change-action="apply"]')).toBeNull()
})

it('read-only hides mutations while status and copying originals remain usable', async () => {
  bridge.desktop.projectChangeStatus.mockResolvedValue(applied)
  bridge.desktop.projectRecoveryOriginal.mockResolvedValue({ text: 'fixture original', bom: false, newline: 'none' })
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  const { host, state } = mount({ receipt: applied, writeAllowed: false })
  for (const action of ['apply', 'revert', 'keep']) expect(host.querySelector(`[data-change-action="${action}"]`)).toBeNull()
  expect(host.textContent).toContain('项目只读')
  await click(host, 'status'); await click(host, 'original')
  expect(writeText).toHaveBeenCalledWith('fixture original')
  expect(bridge.desktop.changeProjectFile).not.toHaveBeenCalled()
  Object.assign(state, { writeAllowed: true }); await nextTick()
  expect(host.querySelector('[data-change-action="revert"]')).not.toBeNull()
})

it('keeps uncertain outcomes query-only and never repeats the write after lookup failures', async () => {
  bridge.desktop.changeProjectFile.mockResolvedValue({ ...applied, state: 'uncertain', can_revert: false })
  bridge.desktop.projectChangeStatus.mockRejectedValueOnce(new Error('Error invoking remote method: Error: [project_change_not_found]')).mockResolvedValueOnce(applied)
  const { host } = mount()
  await click(host, 'apply')
  expect(host.querySelector('[data-change-action="apply"]')).toBeNull()
  expect(host.querySelector('[data-change-action="revert"]')).toBeNull()
  await click(host, 'status')
  expect(host.textContent).toContain('结果尚未确认')
  await click(host, 'status')
  expect(bridge.desktop.changeProjectFile).toHaveBeenCalledTimes(1)
  expect(bridge.desktop.projectChangeStatus).toHaveBeenLastCalledWith('root', 'operation-1')
  expect(host.querySelector('[data-change-action="revert"]')).not.toBeNull()
})

it('preserves the proposal on native cancellation and drops late results from a former root', async () => {
  bridge.desktop.changeProjectFile.mockResolvedValueOnce({ ...applied, recovery_id: '', state: 'cancelled' })
  const { host, state, changed } = mount()
  await click(host, 'apply')
  expect(host.querySelector('[data-change-action="apply"]')).not.toBeNull()
  let resolve!: (value: unknown) => void
  bridge.desktop.changeProjectFile.mockReturnValueOnce(new Promise(done => { resolve = done }))
  host.querySelector<HTMLButtonElement>('[data-change-action="apply"]')!.click(); await nextTick()
  state.projectId = 'other-root'; await nextTick(); resolve(applied); await flush(); await flush()
  expect(changed).not.toHaveBeenCalled()
  expect(host.textContent).not.toContain('已应用')
})

it('treats a mismatched native result as unknown and does not offer another apply', async () => {
  bridge.desktop.changeProjectFile.mockResolvedValueOnce({ ...applied, project_id: 'wrong-root' })
  const { host } = mount()
  await click(host, 'apply')
  expect(host.textContent).toContain('结果尚未确认')
  expect(host.querySelector('[data-change-action="apply"]')).toBeNull()
})
