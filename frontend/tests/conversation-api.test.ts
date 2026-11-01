import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../src/api'

afterEach(() => vi.unstubAllGlobals())

describe('conversation request ownership', () => {
  it('sends the active client when reading, rating and exporting a conversation', async () => {
    const requests: { url: URL; init?: RequestInit }[] = []
    vi.stubGlobal('fetch', async (input: string, init?: RequestInit) => {
      const url = new URL(input, 'http://localhost')
      requests.push({ url, init })
      return url.pathname.endsWith('/export')
        ? new Response('saved conversation', { headers: { 'Content-Disposition': 'attachment; filename="chat.md"' } })
        : Response.json({ messages: [], ok: true, feedback: 'up' })
    })

    await api.conversation('conversation-1', 'browser-1')
    await api.setFeedback('conversation-1', 5, 'up', 'browser-1')
    const exported = await api.exportConversation('conversation-1', 'md', 'browser-1')

    expect(requests.map(row => row.url.searchParams.get('client_id'))).toEqual(['browser-1', 'browser-1', 'browser-1'])
    expect(requests[1].init?.method).toBe('POST')
    expect(JSON.parse(String(requests[1].init?.body))).toEqual({ value: 'up' })
    expect(requests[2].url.searchParams.get('format')).toBe('md')
    expect(exported.name).toBe('chat.md')
    expect(await exported.blob.text()).toBe('saved conversation')
  })

  it('reports a denied history or export instead of returning private data', async () => {
    vi.stubGlobal('fetch', async () => Response.json({ detail: '对话不存在' }, { status: 404 }))
    await expect(api.conversation('private', 'other')).rejects.toThrow('对话不存在')
    await expect(api.exportConversation('private', 'json', 'other')).rejects.toThrow('对话不存在')
  })
})
