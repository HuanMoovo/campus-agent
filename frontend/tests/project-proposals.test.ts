import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../src/api'

afterEach(() => vi.unstubAllGlobals())

describe('project proposal API', () => {
  it('generates explicitly with the selected model and effective reasoning', async () => {
    const calls: Array<[string, RequestInit | undefined]> = []
    vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => { calls.push([url, init]); return Response.json({ id: 'draft' }) })
    await api.projectPropose('root?', { path: 'src/main.ts', instruction: 'Keep the original API', model: 'qwen3', localModel: 'unused', reasoning: 'high' })
    expect(calls[0]?.[0]).toBe('/api/projects/root%3F/proposals')
    expect(calls[0]?.[1]?.method).toBe('POST')
    expect(JSON.parse(String(calls[0]?.[1]?.body))).toEqual({ path: 'src/main.ts', instruction: 'Keep the original API', model: 'qwen', reasoning: 'high' })
  })

  it('sends a local model only for Ollama and omits automatic reasoning', async () => {
    let body: unknown
    vi.stubGlobal('fetch', async (_url: string, init?: RequestInit) => { body = JSON.parse(String(init?.body)); return Response.json({ id: 'draft' }) })
    await api.projectPropose('root', { path: 'a.ts', instruction: 'Simplify', model: 'ollama', localModel: 'local-fixture', reasoning: 'auto' })
    expect(body).toEqual({ path: 'a.ts', instruction: 'Simplify', model: 'ollama', local_model: 'local-fixture' })
  })

  it('checks an existing proposal with GET without generating another one', async () => {
    const calls: Array<[string, RequestInit | undefined]> = []
    vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => { calls.push([url, init]); return Response.json({ id: 'draft', state: 'conflict' }) })
    const result = await api.projectProposal('root?', 'draft/#')
    expect(result.state).toBe('conflict')
    expect(calls).toHaveLength(1)
    expect(calls[0]?.[0]).toBe('/api/projects/root%3F/proposals/draft%2F%23')
    expect(calls[0]?.[1]?.method || 'GET').toBe('GET')
  })

  it('preserves safe proposal error codes and status without exposing server details', async () => {
    vi.stubGlobal('fetch', async () => Response.json({ detail: 'C:/private-root/.env' }, { status: 409, headers: { 'X-Project-Error': 'project_proposal_conflict' } }))
    let failure: any
    try { await api.projectPropose('root', { path: 'a.ts', instruction: 'Simplify', model: 'auto' }) } catch (error) { failure = error }
    expect(failure).toMatchObject({ name: 'ProjectProposalError', code: 'project_proposal_conflict', status: 409 })
    expect(failure.message).not.toContain('private-root')
  })

  it('reports disconnected transport as a typed proposal failure', async () => {
    vi.stubGlobal('fetch', async () => { throw new Error('private network detail') })
    await expect(api.projectProposal('root', 'draft')).rejects.toMatchObject({ name: 'ProjectProposalError', code: 'project_service_unavailable', status: 0 })
  })
})
