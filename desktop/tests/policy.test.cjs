'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const { isOwnUrl, validateWorkspace, parseReadyLine } = require('../lib/policy.cjs')

test('only the exact loopback origin receives desktop privileges', () => {
  const origin = 'http://127.0.0.1:53212'
  assert.equal(isOwnUrl(`${origin}/api/health`, origin), true)
  for (const url of ['http://127.0.0.1:53213', 'https://127.0.0.1:53212', 'http://127.0.0.1.example:53212',
    'http://user:pass@127.0.0.1:53212', 'file:///C:/secret', 'javascript:alert(1)', 'http://localhost:53212']) {
    assert.equal(isOwnUrl(url, origin), false, url)
  }
  assert.equal(isOwnUrl(origin, null), false)
})

test('workspace IPC cannot write arbitrary keys or invalid values', () => {
  assert.deepEqual(validateWorkspace({ model: 'qwen3', conversationId: '123-abcd' }), { model: 'qwen3', conversationId: '123-abcd' })
  assert.deepEqual(validateWorkspace({ conversationId: '' }), { conversationId: '' })
  const appearance = { appearance: 'system', accentColor: '#A1b2c3', localModel: 'hf.co/user/model:Q4_K_M' }
  assert.deepEqual(validateWorkspace(appearance), appearance)
  for (const value of [null, [], 'abc', { model: 'other' }, { filename: '../config' }, { conversationId: '../config' },
    { conversationId: 'a'.repeat(65) }, { conversationId: 12 }, { appearance: 'unknown' }, { accentColor: 'red' },
    { accentColor: '#fff; color:red' }, { accentColor: null }, { localModel: 12 }, { localModel: 'a'.repeat(129) },
    { localModel: 'bad\nmodel' }]) assert.throws(() => validateWorkspace(value))
})

test('startup accepts only a matching nonce and valid loopback port', () => {
  const ready = { event: 'campus-ready', nonce: 'secret', host: '127.0.0.1', port: 53212 }
  assert.deepEqual(parseReadyLine(JSON.stringify(ready), 'secret'), { origin: 'http://127.0.0.1:53212', port: 53212 })
  assert.equal(parseReadyLine('log line', 'secret'), null)
  for (const update of [{ nonce: 'wrong' }, { host: '0.0.0.0' }, { port: 80 }, { port: 65536 }, { port: '53212' }, { event: 'something' }]) {
    assert.equal(parseReadyLine(JSON.stringify({ ...ready, ...update }), 'secret'), null)
  }
})
