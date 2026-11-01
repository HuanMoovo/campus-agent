import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { createApp, h, nextTick, reactive } from 'vue'
import AgentDiagnostics from '../src/components/AgentDiagnostics.vue'
import { createUserMessage, readAgentMetadata, regenerationRequest, toConversationMessage } from '../src/agent-diagnostics'
import { setLocale } from '../src/i18n'
import type { AgentRun, ChatPhase, ContextReport } from '../src/api'

const context: ContextReport = { limit_chars: 24000, input_chars: 18000, history_available: 12, history_used: 8, history_omitted: 4, sources_used: 2, sources_omitted: 1, sources_truncated: 1, attachments_used: 1, attachments_truncated: 1, trimmed: true }
const run: AgentRun = { id: 'private-run-id', status: 'partial', duration_ms: 1250, steps: [{ phase: 'retrieve', status: 'completed', duration_ms: 40 }, { phase: 'answer', status: 'failed', duration_ms: 1210 }] }
const task = { kind: 'campus_reads' as const, limit_steps: 3 as const, planned_steps: 3, attempted_steps: 2, completed_steps: 1, limit_ms: 20000 as const, stop_reason: 'deadline' as const, truncated_results: 1 }
const cleanup: (() => void)[] = []

function mount(props: { phase?: ChatPhase; context?: ContextReport; run?: AgentRun }) {
  const host = document.createElement('div')
  document.body.append(host)
  const app = createApp({ render: () => h(AgentDiagnostics, props) })
  app.mount(host)
  cleanup.push(() => { app.unmount(); host.remove() })
  return host
}

beforeEach(() => setLocale('zh'))
afterEach(() => cleanup.splice(0).forEach(dispose => dispose()))

describe('compact agent diagnostics', () => {
  it('shows localized waiting phases and removes waiting text on termination', async () => {
    const props = reactive<{ phase?: ChatPhase }>({ phase: 'preparing' })
    const host = mount(props)
    expect(host.querySelector('[role="status"]')?.textContent).toContain('准备')
    props.phase = 'answering'
    await nextTick()
    expect(host.querySelector('[role="status"]')?.textContent).toContain('生成')
    setLocale('en')
    await nextTick()
    expect(host.querySelector('[role="status"]')?.textContent).toContain('Generating')
    props.phase = undefined
    await nextTick()
    expect(host.querySelector('[role="status"]')).toBeNull()
  })

  it('shows omission counts only when trimmed and keeps the run collapsed', async () => {
    const props = reactive({ context, run })
    const host = mount(props)
    const notice = host.querySelector('.context-notice')?.textContent || ''
    expect(notice).toContain('4')
    expect(notice).toContain('较早消息')
    expect(notice).toContain('附件')
    expect(notice.toLowerCase()).not.toContain('token')
    expect(host.querySelector<HTMLDetailsElement>('details')?.open).toBe(false)
    expect(host.querySelector('summary')?.textContent).toContain('未完成')
    expect(host.querySelector('summary')?.textContent).toContain('1.25')
    expect(host.textContent).toContain('检索资料')
    expect(host.textContent).toContain('失败')
    expect(host.textContent).not.toContain('private-run-id')
    props.context = { ...context, trimmed: false }
    await nextTick()
    expect(host.querySelector('.context-notice')).toBeNull()
  })

  it('adds no diagnostic furniture for an old response', () => {
    expect(mount({}).textContent).toBe('')
    expect(mount({ run }).querySelector('.run-task')).toBeNull()
  })

  it('retains only safe task budget fields after reloading history', () => {
    const result = toConversationMessage({ role: 'assistant', content: '已取得成绩，课表未完成', created_at: '', run: { ...run, task: { ...task, prompt: 'private', arguments: { token: 'private' }, raw_error: 'private' } } } as never)
    expect(result.text).toBe('已取得成绩，课表未完成')
    expect(result.run?.task).toEqual(task)
    expect(JSON.stringify(result.run)).not.toContain('private"')
    expect(result.partial).toBe(true)
  })

  it.each([
    { kind: 'unknown' }, { limit_steps: 4 }, { limit_ms: 20001 },
    { planned_steps: -1 }, { planned_steps: 5 }, { planned_steps: 1.5 },
    { attempted_steps: NaN }, { attempted_steps: Infinity }, { attempted_steps: 4 },
    { planned_steps: 1, attempted_steps: 2 }, { completed_steps: 3 },
    { truncated_results: -1 }, { truncated_results: 2 }, { stop_reason: 'private-error' },
  ])('drops malformed task %j while keeping the answer and valid run', patch => {
    const result = toConversationMessage({ role: 'assistant', content: '可显示回答', created_at: '', run: { ...run, task: { ...task, ...patch } } } as never)
    expect(result.text).toBe('可显示回答')
    expect(result.run).toEqual(run)
  })

  it('shows localized budget and stop reasons inside the existing collapsed details', async () => {
    const props = reactive({ phase: 'querying' as ChatPhase, run: { ...run, task } })
    const host = mount(props)
    const details = host.querySelector<HTMLDetailsElement>('details')!
    expect(details.open).toBe(false)
    expect(details.querySelector('.run-task')?.textContent).toContain('2 / 3')
    expect(details.textContent).toContain('达到等待时限')
    expect(details.textContent).toContain('1 项结果已截短')
    expect(host.querySelector('[role="status"]')?.textContent).toContain('查询校园信息')
    setLocale('en')
    await nextTick()
    expect(details.textContent).toContain('Time budget reached')
    expect(details.textContent).toContain('1 result(s) shortened')
    expect(host.querySelector('[role="status"]')?.textContent).toContain('Querying campus information')
    props.run = { ...run, task: { ...task, stop_reason: 'completed' } } as never
    await nextTick()
    expect(details.textContent).toContain('All requested reads completed')
    expect(details.textContent).not.toContain('Time budget reached')
    setLocale('ja')
    await nextTick()
    expect(details.textContent).toContain('指定した照会が完了')
    expect(host.querySelector('[role="status"]')?.textContent).toContain('学内情報を照会')
    expect(host.textContent).not.toContain('campus_reads')
    expect(host.querySelectorAll('details')).toHaveLength(1)
  })

  it('keeps history diagnostics and marks a partial response incomplete', () => {
    const result = toConversationMessage({ id: 7, role: 'assistant', content: '部分答复', created_at: '', partial: true, context, run, sources: [{ title: '通知' }], tool_calls: [{ name: 'schedule' }], thinking: '已分析', feedback: 'up' })
    expect(result).toMatchObject({ id: 7, text: '部分答复', partial: true, context, run, sources: [{ title: '通知' }], tools: ['schedule'], thinking: '已分析', feedback: 'up' })
    expect(result.streaming).not.toBe(true)
  })

  it('does not surface extra raw diagnostics or malformed step labels', () => {
    const data = readAgentMetadata({ context: { ...context, raw_error: 'sk-secret' }, run: { ...run, raw_error: 'sk-secret', steps: [...run.steps, { phase: 'sk-secret', status: 'failed', duration_ms: 1 }] } })
    expect(JSON.stringify(data)).not.toContain('sk-secret')
    expect(data.run?.steps).toHaveLength(2)
  })

  it('regenerates the original question with the same in-memory attachments', () => {
    const attachments = [{ name: '成绩.txt', text: '这是待分析材料' }]
    const user = createUserMessage('解释材料', attachments)
    attachments[0].text = 'changed outside the conversation'
    const request = regenerationRequest(user, { role: 'assistant', text: '答复', context })
    expect(user.text).toContain('[附件] 成绩.txt')
    expect(request).toEqual({ text: '解释材料', attachments: [{ name: '成绩.txt', text: '这是待分析材料' }], missingAttachments: false })
  })

  it('requires reattachment after history reload and uses explicit replacement files', () => {
    const user = toConversationMessage({ role: 'user', content: '解释材料', created_at: '' })
    const assistant = toConversationMessage({ role: 'assistant', content: '旧回答', created_at: '', context })
    expect(regenerationRequest(user, assistant).missingAttachments).toBe(true)
    expect(regenerationRequest(user, assistant, [{ name: '重附.txt', text: '重新提供' }])).toEqual({ text: '解释材料', attachments: [{ name: '重附.txt', text: '重新提供' }], missingAttachments: false })
    expect(regenerationRequest(user, { role: 'assistant', text: '旧服务端回答' }).missingAttachments).toBe(false)
  })
})
