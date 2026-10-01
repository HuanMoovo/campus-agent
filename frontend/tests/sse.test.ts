import { describe, expect, it } from 'vitest'

import { parseSseFrame } from '../src/api'

describe('parseSseFrame', () => {
  it('parses event and data lines', () => {
    expect(parseSseFrame('event: delta\ndata: {"text": "你好"}')).toEqual({ event: 'delta', data: { text: '你好' } })
  })

  it('joins multi-line data and tolerates missing spaces', () => {
    expect(parseSseFrame('event:done\ndata:{"answer":\ndata: "a"}')).toEqual({ event: 'done', data: { answer: 'a' } })
  })

  it('defaults the event name to message', () => {
    expect(parseSseFrame('data: {"ok": true}')).toEqual({ event: 'message', data: { ok: true } })
  })

  it('returns null for frames without data or with invalid json', () => {
    expect(parseSseFrame('event: ping')).toBeNull()
    expect(parseSseFrame('data: not-json')).toBeNull()
    expect(parseSseFrame('data: 42')).toBeNull()
    expect(parseSseFrame('data: "text"')).toBeNull()
    expect(parseSseFrame('')).toBeNull()
  })
})
