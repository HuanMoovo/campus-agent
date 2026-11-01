import { afterEach, describe, expect, it, vi } from 'vitest'
import { chatStream, ChatStreamError } from '../src/api'

const context = { limit_chars: 24000, input_chars: 18000, history_available: 12, history_used: 8, history_omitted: 4, sources_used: 2, sources_omitted: 1, sources_truncated: 1, attachments_used: 1, attachments_truncated: 0, trimmed: true }
const run = { id: 'run-1', status: 'completed', duration_ms: 1240, steps: [{ phase: 'retrieve', status: 'completed', duration_ms: 40 }, { phase: 'answer', status: 'completed', duration_ms: 1200 }] }
const source = { title: '通知', snippet: '申请说明' }
const payload = { message: '怎么申请？', conversationId: '', model: 'auto', clientId: 'browser-1' }
const event = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`

function serve(frames: string[]) {
  vi.stubGlobal('fetch', async () => new Response(new ReadableStream({
    start(controller) {
      const encoder = new TextEncoder()
      for (const frame of frames) controller.enqueue(encoder.encode(frame))
      controller.close()
    },
  }), { headers: { 'Content-Type': 'text/event-stream' } }))
}

afterEach(() => vi.unstubAllGlobals())

describe('agent stream status and metadata', () => {
  it('delivers recognized phases and preserves done diagnostics', async () => {
    serve([event('status', { phase: 'preparing' }), event('status', { phase: 'querying' }), event('status', { phase: 'answering' }), event('delta', { text: '答复' }), event('done', { conversation_id: 'chat-1', answer: '答复', sources: [source], context, run })])
    const phases: string[] = []
    const result = await chatStream(payload, { onStatus: phase => phases.push(phase) }, new AbortController().signal)
    expect(phases).toEqual(['preparing', 'querying', 'answering'])
    expect(result.context).toEqual(context)
    expect(result.run).toEqual(run)
    expect(result.answer).toBe('答复')
  })

  it('ignores malformed optional events and supports an older server', async () => {
    serve([event('status', null), event('status', { phase: {} }), event('status', { phase: 'secret' }), event('status', ['answering']), event('done', { answer: '旧版回答', sources: [], context: { trimmed: 'true' }, run: { steps: 'bad' } })])
    const phases: string[] = []
    const result = await chatStream(payload, { onStatus: phase => phases.push(phase) }, new AbortController().signal)
    expect(phases).toEqual([])
    expect(result.answer).toBe('旧版回答')
    expect(result.context).toBeUndefined()
    expect(result.run).toBeUndefined()
  })

  it('does not let malformed run fields discard an otherwise valid answer', async () => {
    serve([event('done', { answer: '可显示回答', sources: [], run: { id: 'run-bad', status: { toString: 'invalid' }, duration_ms: 0, steps: [] } })])
    await expect(chatStream(payload, {}, new AbortController().signal)).resolves.toMatchObject({ answer: '可显示回答' })
  })

  it('keeps a valid answer and run when an optional task is malformed', async () => {
    serve([event('done', { answer: '可显示回答', sources: [], run: { ...run, task: { kind: 'campus_reads', raw_error: 'private' } } })])
    const result = await chatStream(payload, {}, new AbortController().signal)
    expect(result.answer).toBe('可显示回答')
    expect(result.run).toEqual(run)
  })

  it('keeps preparation metadata and a partial run when generation fails', async () => {
    serve([event('meta', { conversation_id: 'chat-2', sources: [source], context }), event('delta', { text: '已生成' }), event('error', { message: '生成中断', run: { ...run, status: 'partial' }, tool_calls: [{ name: 'schedule' }] })])
    let caught: unknown
    try { await chatStream(payload, {}, new AbortController().signal) } catch (error) { caught = error }
    expect(caught).toBeInstanceOf(ChatStreamError)
    expect(caught).toMatchObject({ partial: '已生成', metadata: { conversation_id: 'chat-2', sources: [source], context, run: { ...run, status: 'partial' }, tool_calls: [{ name: 'schedule' }] } })
  })

  it('preserves known diagnostics if the transport closes without a done event', async () => {
    serve([event('meta', { conversation_id: 'chat-3', sources: [source], context }), event('delta', { text: '未完成' })])
    await expect(chatStream(payload, {}, new AbortController().signal)).rejects.toMatchObject({ partial: '未完成', metadata: { conversation_id: 'chat-3', context, sources: [source] } })
  })

  it('receives preparation diagnostics before output and marks interrupted runs incomplete', async () => {
    const preparingRun = { ...run, status: 'running' }
    serve([event('meta', { conversation_id: 'chat-4' }), event('status', { phase: 'answering', sources: [source], context, run: preparingRun }), event('delta', { text: '未完成' })])
    const observed: unknown[] = []
    await expect(chatStream(payload, { onStatus: (...args) => observed.push(args) }, new AbortController().signal)).rejects.toMatchObject({
      partial: '未完成', metadata: { sources: [source], context, run: { ...run, status: 'partial' } },
    })
    expect(observed).toEqual([['answering', expect.objectContaining({ context, run: preparingRun })]])
  })

  it('accepts the terminal done event without waiting for a healthy connection close', async () => {
    vi.stubGlobal('fetch', async () => new Response(new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode(event('done', { answer: '已完成', sources: [], run }))) },
      pull(controller) { controller.error(new Error('connection closed after final event')) },
    })))
    await expect(chatStream(payload, {}, new AbortController().signal)).resolves.toMatchObject({ answer: '已完成', run })
  })
})
