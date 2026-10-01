'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const http = require('node:http')
const { startBackend, request } = require('../lib/backend.cjs')
const { version: expectedVersion } = require('../package.json')

function send(origin, route, token, { method = 'GET', body } = {}) {
  return new Promise((resolve, reject) => {
    const payload = body === undefined ? undefined : JSON.stringify(body)
    const headers = token ? { 'X-Campus-Desktop-Token': token } : {}
    if (payload !== undefined) {
      headers['Content-Type'] = 'application/json'
      headers['Content-Length'] = Buffer.byteLength(payload)
    }
    const req = http.request(origin + route, { method, headers }, res => {
      let text = ''
      res.setEncoding('utf8')
      res.on('data', chunk => { text += chunk })
      res.on('end', () => resolve({ status: res.statusCode, text }))
      res.on('error', reject)
    })
    req.setTimeout(15000, () => req.destroy(new Error(`${method} ${route} timed out`)))
    req.on('error', reject)
    req.end(payload)
  })
}

async function json(origin, route, token, options) {
  const response = await send(origin, route, token, options)
  assert.equal(response.status, 200, `${options?.method || 'GET'} ${route}: ${response.text}`)
  return JSON.parse(response.text)
}

test('desktop backend supports authenticated knowledge, chat history and clean shutdown', { timeout: 60000 }, async t => {
  const projectRoot = path.resolve(__dirname, '..', '..')
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'campus-desktop-node-'))
  const packaged = process.env.CAMPUS_TEST_PACKAGED === '1'
  let unexpectedExit = false
  // Keep the smoke test deterministic and prevent inherited model keys from
  // making paid network requests; startBackend copies this env synchronously.
  const testEnvironment = { QWEN_API_KEY: '', DEEPSEEK_API_KEY: '', ENABLE_RAG: 'false', LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' }
  const previousEnvironment = Object.fromEntries(Object.keys(testEnvironment).map(key => [key, process.env[key]]))
  let backend
  try {
    Object.assign(process.env, testEnvironment)
    backend = startBackend({
      projectRoot, dataDir, packaged, resourcesPath: path.join(projectRoot, 'build'),
      frontendDirectory: path.join(projectRoot, 'frontend', 'dist'),
      backendExecutable: packaged ? path.join(projectRoot, 'build', 'backend', 'campus-backend', 'campus-backend.exe') : undefined,
      onExit: () => { unexpectedExit = true }, timeout: 40000,
    })
  } finally {
    for (const [key, value] of Object.entries(previousEnvironment)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  }
  t.after(async () => {
    await backend.stop()
    const resolved = path.resolve(dataDir)
    assert.ok(resolved.startsWith(path.resolve(os.tmpdir()) + path.sep))
    assert.ok(path.basename(resolved).startsWith('campus-desktop-node-'))
    fs.rmSync(resolved, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
  })
  const { origin, token } = await backend.ready
  assert.equal((await request(origin, '/api/health', token)).status, 'ok')
  assert.equal((await send(origin, '/api/health')).status, 401)
  assert.equal((await send(origin, '/', 'wrong')).status, 401)
  const frontend = await send(origin, '/', token)
  assert.equal(frontend.status, 200)
  assert.match(frontend.text, /<div id="app"><\/div>/)
  assert.equal(fs.existsSync(path.join(dataDir, 'campus.db')), true)

  await t.test('running API reports the desktop release version', async () => {
    const schema = await json(origin, '/openapi.json', token)
    assert.equal(schema.info.title, 'Mens API')
    assert.equal(schema.info.version, expectedVersion)
  })

  await t.test('model and campus configuration plus optional Baike plugin work in the shipped backend', async () => {
    const key = 'mens-integration-not-a-real-key'
    const configure = { method: 'PUT', body: { api_key: key, model: 'qwen-test' } }
    assert.equal((await send(origin, '/api/models/config/qwen', undefined, configure)).status, 401)
    const saved = await json(origin, '/api/models/config/qwen', token, configure)
    assert.equal(saved.providers.qwen.configured, true)
    assert.equal(JSON.stringify(saved).includes(key), false)
    assert.equal(fs.readFileSync(path.join(dataDir, 'model-providers.json'), 'utf8').includes(key), false)
    await json(origin, '/api/models/config/qwen', token, { method: 'PUT', body: { clear_api_key: true } })
    assert.equal((await json(origin, '/api/models/config', token)).providers.qwen.configured, false)
    const sources = await json(origin, '/api/campus-sources', token)
    assert.equal(sources.length, 9)
    assert.ok(sources.every(source => !source.configured && !source.has_token))
    const catalog = await json(origin, '/api/plugins/catalog', token)
    assert.deepEqual(catalog.map(plugin => plugin.id), ['openalex', 'crossref', 'baidu_baike'])
    const install = { method: 'POST', body: { id: 'baidu_baike' } }
    assert.equal((await send(origin, '/api/plugins/catalog/install', undefined, install)).status, 401)
    const plugin = await json(origin, '/api/plugins/catalog/install', token, install)
    const response = await json(origin, '/api/plugins/baidu_baike_search/invoke', token, {
      method: 'POST', body: { bk_key: '人工智能' },
    })
    assert.equal(response.result.external, true)
    const url = new URL(response.result.url)
    assert.equal(url.origin, 'https://baike.baidu.com')
    assert.equal(url.searchParams.get('word'), '人工智能')
    await json(origin, `/api/plugins/${plugin.id}`, token, { method: 'DELETE' })
    assert.equal((await json(origin, '/api/plugins/catalog', token)).find(row => row.id === 'baidu_baike').installed, false)
  })

  const title = '桌面打包验收：冰晶图书馆通行证'
  const originalContent = '冰晶图书馆通行证仅在北门服务台领取。'
  const updatedContent = '冰晶图书馆通行证改为南门服务台领取，开放时间为09:00至17:00。'
  let documentId
  let conversationId

  await t.test('knowledge creation rejects missing credentials and saves UTF-8 content', async () => {
    const before = await json(origin, '/api/documents', token)
    const create = { method: 'POST', body: { title, content: originalContent } }
    assert.equal((await send(origin, '/api/documents', undefined, create)).status, 401)
    assert.deepEqual(await json(origin, '/api/documents', token), before)
    const created = await json(origin, '/api/documents', token, create)
    assert.equal(created.title, title)
    assert.equal(created.content, originalContent)
    assert.equal(created.index_status, 'keyword')
    assert.equal(typeof created.id, 'string')
    documentId = created.id
    const saved = (await json(origin, '/api/documents', token)).find(row => row.id === documentId)
    assert.equal(saved?.content, originalContent)
  })

  await t.test('chat retrieves the new document and persists messages with sources', async () => {
    const question = '冰晶图书馆通行证如何领取？'
    const answer = await json(origin, '/api/chat', token, { method: 'POST', body: { message: question, model: 'auto' } })
    assert.equal(answer.mode, 'demo')
    assert.match(answer.answer, /北门服务台/)
    assert.ok(answer.sources.some(source => source.title === title && source.snippet === originalContent))
    conversationId = answer.conversation_id
    assert.equal(typeof conversationId, 'string')
    assert.ok(conversationId.length > 0)
    const history = await json(origin, `/api/conversations/${conversationId}`, token)
    assert.equal(history.id, conversationId)
    assert.deepEqual(history.messages.map(row => row.role), ['user', 'assistant'])
    assert.equal(history.messages[0].content, question)
    assert.equal(history.messages[1].content, answer.answer)
    assert.deepEqual(history.messages[1].sources, answer.sources)
  })

  await t.test('knowledge update is used by a follow-up in the same conversation', async () => {
    const updated = await json(origin, `/api/documents/${documentId}`, token, {
      method: 'PUT', body: { title, content: updatedContent },
    })
    assert.equal(updated.id, documentId)
    assert.equal(updated.content, updatedContent)
    assert.equal((await json(origin, '/api/documents', token)).find(row => row.id === documentId)?.content, updatedContent)
    const question = '冰晶图书馆通行证现在如何领取？'
    const answer = await json(origin, '/api/chat', token, {
      method: 'POST', body: { message: question, conversation_id: conversationId },
    })
    assert.equal(answer.conversation_id, conversationId)
    assert.ok(answer.sources.some(source => source.title === title && source.snippet === updatedContent))
    assert.ok(answer.sources.every(source => source.snippet !== originalContent))
    assert.match(answer.answer, /南门服务台/)
    const history = await json(origin, `/api/conversations/${conversationId}`, token)
    assert.deepEqual(history.messages.map(row => row.role), ['user', 'assistant', 'user', 'assistant'])
    assert.equal(history.messages[2].content, question)
    assert.equal(history.messages[3].content, answer.answer)
    assert.deepEqual(history.messages[3].sources, answer.sources)
    assert.ok(history.messages[1].sources.some(source => source.snippet === originalContent))
  })

  await t.test('knowledge deletion removes retrieval results without erasing saved history', async () => {
    assert.deepEqual(await json(origin, `/api/documents/${documentId}`, token, { method: 'DELETE' }), { deleted: true })
    assert.ok((await json(origin, '/api/documents', token)).every(row => row.id !== documentId))
    assert.equal((await send(origin, `/api/documents/${documentId}`, token, { method: 'DELETE' })).status, 404)
    const answer = await json(origin, '/api/chat', token, {
      method: 'POST', body: { message: '冰晶图书馆通行证如何领取？' },
    })
    assert.ok(answer.sources.every(source => source.title !== title))
    const history = await json(origin, `/api/conversations/${conversationId}`, token)
    assert.equal(history.messages.length, 4)
    assert.ok(history.messages[3].sources.some(source => source.snippet === updatedContent))
  })

  await backend.stop()
  assert.equal(unexpectedExit, false)
  await assert.rejects(send(origin, '/api/health', token))
})
