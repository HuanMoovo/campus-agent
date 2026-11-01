import { afterEach, describe, expect, it, vi } from 'vitest'
import { chatStream, api } from '../src/api'
import { createUserMessage } from '../src/agent-diagnostics'
import { projectRegeneration, projectSourceLabel } from '../src/project-files'

afterEach(() => vi.unstubAllGlobals())

describe('project question references', () => {
  it('sends only explicit relative references, never preview contents or native root paths', async () => {
    let body: any
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => {
      body = JSON.parse(String(init.body))
      return new Response(`event: done\ndata: ${JSON.stringify({ answer: 'ok', sources: [] })}\n\n`)
    })
    await chatStream({ message: 'review', conversationId: '', model: 'auto', clientId: 'fixture', project: { id: 'opaque', files: ['src/main.ts'] } }, {}, new AbortController().signal)
    expect(body.project).toEqual({ id: 'opaque', files: ['src/main.ts'] })
    expect(body.attachments).toBeUndefined()
    expect(body.message).toBe('review')
  })

  it('uses escaped API paths and only relative read requests', async () => {
    const calls: Array<[string, RequestInit | undefined]> = []
    vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => { calls.push([url, init]); return Response.json({}) })
    await api.projectFiles('opaque?', 'src/ui')
    await api.projectRead('opaque?', 'src/ui/main.ts')
    await api.closeProject('opaque?')
    expect(calls[0]?.[0]).toBe('/api/projects/opaque%3F/files?path=src%2Fui')
    expect(JSON.parse(String(calls[1]?.[1]?.body))).toEqual({ path: 'src/ui/main.ts' })
    expect(calls[2]?.[1]?.method).toBe('DELETE')
  })

  it('supports the same reference-only project context in synchronous chat', async () => {
    let body: any
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => { body = JSON.parse(String(init.body)); return Response.json({ answer: 'ok', sources: [] }) })
    await api.chat('review', '', 'auto', undefined, 'fixture', false, { id: 'opaque', files: ['main.ts'] })
    expect(body.project).toEqual({ id: 'opaque', files: ['main.ts'] })
    expect(body.attachments).toBeUndefined()
  })

  it('keeps an in-memory user marker and re-reads the same project files for retry', () => {
    const project = { id: 'a', files: ['main.ts'] }
    const user = createUserMessage('review', [], project)
    project.files.push('other.ts')
    expect(user.text).toBe('review\n\n[项目文件] main.ts')
    expect(projectRegeneration(user, { role: 'assistant', text: '' }, { id: 'a', files: [] })).toEqual({ project: { id: 'a', files: ['main.ts'] }, missingProject: false })
    expect(projectRegeneration(user, { role: 'assistant', text: '' }, { id: 'b', files: ['main.ts'] }).missingProject).toBe(true)
  })

  it('blocks history retries even if another active project has matching relative paths', () => {
    const user = { role: 'user' as const, text: 'review\n\n[项目文件] src/a.ts、src/b.ts' }
    const assistant = { role: 'assistant' as const, text: 'ok', sources: [{ title: 'src/a.ts', kind: 'project', path: 'src/a.ts' }] }
    expect(projectRegeneration(user, assistant, null).missingProject).toBe(true)
    expect(projectRegeneration(user, assistant, { id: 'new', files: ['unrelated.ts'] }).missingProject).toBe(true)
    expect(projectRegeneration(user, assistant, { id: 'new', files: ['src/b.ts', 'src/a.ts'] })).toEqual({ missingProject: true })
    expect(projectRegeneration({ role: 'user', text: 'no marker' }, assistant, null).missingProject).toBe(true)
    expect(projectRegeneration({ role: 'user', text: 'ordinary' }, { role: 'assistant', text: 'ok' }, { id: 'new', files: ['unrelated.ts'] })).toEqual({ missingProject: false })
  })

  it('shows project citations as relative paths with line ranges', () => {
    expect(projectSourceLabel({ title: 'a', kind: 'project', path: 'src/a.ts', start_line: 2, end_line: 8 })).toBe('src/a.ts:2–8')
  })
})
